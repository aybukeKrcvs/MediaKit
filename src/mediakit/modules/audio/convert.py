"""Audio format conversion with PyAV (FFmpeg's libraries, in-process).

The pipeline, in FFmpeg's own vocabulary:

    container  the file (an .m4a, an .mp4 video, ...)
      stream   one track inside it; we take the first audio one
      packet   a chunk of *compressed* data, as stored in the file
      frame    decoded PCM samples, after the decoder ran on packets

    input container --demux--> packets --decode--> frames
        --resample--> frames in the encoder's format/rate/layout
        --encode--> packets --mux--> output container

The resampler sits in the middle because every encoder has demands:
AAC only takes planar float ("fltp"), Opus only 8/12/16/24/48 kHz, and
most encoders want frames of exactly `frame_size` samples (AAC 1024,
MP3 1152, Opus 960). AudioResampler handles all three at once.

Pure Python + PyAV. No Qt.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import av

from mediakit.core.batch import Cancelled, CancelToken, WorkFn
from mediakit.core.paths import ConflictPolicy, resolve_output_path

# on_progress(done, total) -- done/total in milliseconds of audio
Progress = Callable[[int, int], None]

# Anything FFmpeg can open that usually carries audio, video included
# (converting a video to MP3 is the most common "extract the sound").
INPUT_EXTENSIONS: frozenset[str] = frozenset(
    {
        "mp3", "wav", "flac", "ogg", "oga", "opus", "m4a", "aac", "wma", "aif", "aiff",
        "amr", "3gp", "mp4", "mkv", "mov", "webm", "avi",
    }
)  # fmt: skip


@dataclass(frozen=True)
class AudioFormat:
    key: str
    extension: str
    muxer: str  # FFmpeg container name
    codec: str  # FFmpeg encoder name
    bitrates: tuple[int, ...]  # kbit/s choices; empty = lossless
    default_bitrate: int = 0

    @property
    def lossless(self) -> bool:
        return not self.bitrates


FORMATS: dict[str, AudioFormat] = {
    "mp3": AudioFormat("mp3", "mp3", "mp3", "libmp3lame", (128, 192, 256, 320), 192),
    # "ipod" is FFmpeg's .m4a flavour of the MP4 container.
    "m4a": AudioFormat("m4a", "m4a", "ipod", "aac", (96, 128, 192, 256), 192),
    "opus": AudioFormat("opus", "opus", "opus", "libopus", (48, 64, 96, 128, 160), 96),
    "flac": AudioFormat("flac", "flac", "flac", "flac", ()),
    "wav": AudioFormat("wav", "wav", "wav", "pcm_s16le", ()),
}
# No OGG/Vorbis: the PyAV wheels ship only FFmpeg's built-in Vorbis
# encoder, which FFmpeg itself marks experimental. Opus replaces it and
# is better at every bitrate.

SAMPLE_RATES: tuple[int, ...] = (8000, 16000, 22050, 24000, 32000, 44100, 48000)
MAX_CHANNELS = 2  # everything here is for listening or speech, not surround


@dataclass(frozen=True)
class AudioInfo:
    codec: str
    sample_rate: int
    channels: int
    duration: float  # seconds; 0 if the container does not say
    bitrate: int  # bit/s; 0 if unknown


def _audio_stream(container: av.container.InputContainer) -> av.audio.AudioStream:
    if not container.streams.audio:
        raise ValueError("No audio track in this file.")
    return container.streams.audio[0]


def _duration(container: av.container.InputContainer, stream: av.audio.AudioStream) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / av.time_base
    return 0.0


def probe(path: Path) -> AudioInfo:
    """What is inside a file, without decoding it."""
    with av.open(str(path)) as container:
        stream = _audio_stream(container)
        ctx = stream.codec_context
        return AudioInfo(
            codec=ctx.name,
            sample_rate=ctx.sample_rate,
            channels=ctx.channels,
            duration=_duration(container, stream),
            bitrate=ctx.bit_rate or container.bit_rate or 0,
        )


def pick_rate(codec: str, wanted: int) -> int:
    """`wanted` if the encoder accepts it, else the closest it does,
    preferring a higher rate (never throw detail away by accident)."""
    allowed = av.codec.Codec(codec, "w").audio_rates
    if not allowed or wanted in allowed:
        return wanted
    higher = [r for r in allowed if r >= wanted]
    return min(higher) if higher else max(allowed)


def convert(
    source: Path,
    destination: Path,
    fmt: AudioFormat,
    bitrate: int = 0,
    sample_rate: int | None = None,
    channels: int | None = None,
    on_progress: Progress | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Transcode the first audio track of `source` into `destination`.

    sample_rate / channels None = keep the source's (channels capped at
    stereo). Written to a .part file and renamed at the end, so a failure
    or a cancel never leaves a half-written file under the real name.
    """
    partial = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with av.open(str(source)) as inp:
            in_stream = _audio_stream(inp)
            in_ctx = in_stream.codec_context
            total_ms = round(_duration(inp, in_stream) * 1000)

            rate = pick_rate(fmt.codec, sample_rate or in_ctx.sample_rate)
            layout = "mono" if (channels or min(in_ctx.channels, MAX_CHANNELS)) == 1 else "stereo"

            with av.open(str(partial), "w", format=fmt.muxer) as out:
                out.metadata.update(inp.metadata)  # title, artist, ...
                out_stream = out.add_stream(fmt.codec, rate=rate, layout=layout)
                ctx = out_stream.codec_context
                if not fmt.lossless:
                    ctx.bit_rate = (bitrate or fmt.default_bitrate) * 1000
                resampler = av.AudioResampler(
                    format=ctx.codec.audio_formats[0].name,
                    layout=layout,
                    rate=rate,
                    frame_size=ctx.frame_size or None,
                )

                def encode(frame: av.AudioFrame | None) -> None:
                    for resampled in resampler.resample(frame):
                        out.mux(out_stream.encode(resampled))
                    if frame is None:  # end: drain the encoder too
                        out.mux(out_stream.encode(None))

                for packet in inp.demux(in_stream):
                    if cancel is not None and cancel.cancelled:
                        raise Cancelled
                    for frame in packet.decode():
                        encode(frame)
                        if on_progress and total_ms and frame.time is not None:
                            on_progress(min(round(frame.time * 1000), total_ms), total_ms)
                encode(None)
        partial.replace(destination)
        return destination
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()


def make_audio_convert_job(
    out_dir: Path | None,
    policy: ConflictPolicy,
    format_key: str,
    bitrate: int = 0,
    sample_rate: int | None = None,
    channels: int | None = None,
    on_progress: Progress | None = None,
    cancel: CancelToken | None = None,
) -> WorkFn:
    fmt = FORMATS[format_key]

    def work(source: Path) -> Path | None:
        directory = out_dir if out_dir is not None else source.parent
        destination = resolve_output_path(source, directory, fmt.extension, policy)
        if destination is None:
            return None
        return convert(
            source, destination, fmt, bitrate, sample_rate, channels, on_progress, cancel
        )

    return work
