"""Phase 2a: audio format conversion with PyAV."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import av
import numpy as np
import pytest

from mediakit.core.batch import Cancelled, CancelToken, run_batch
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.audio.convert import (
    FORMATS,
    convert,
    make_audio_convert_job,
    pick_rate,
    probe,
)

RATE = 44100
SECONDS = 2.0


def write_tone(path: Path, codec="pcm_s16le", fmt=None, title=None, channels=2):
    """A stereo 440 Hz tone, written with PyAV itself."""
    t = np.arange(int(RATE * SECONDS)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    layout = "stereo" if channels == 2 else "mono"
    planes = np.stack([tone] * channels)
    with av.open(str(path), "w", format=fmt) as out:
        if title:
            out.metadata["title"] = title
        stream = out.add_stream(codec, rate=RATE, layout=layout)
        resampler = av.AudioResampler(
            format=stream.codec_context.codec.audio_formats[0].name,
            layout=layout,
            rate=RATE,
            frame_size=stream.codec_context.frame_size or None,
        )
        frame = av.AudioFrame.from_ndarray(planes, format="fltp", layout=layout)
        frame.sample_rate = RATE
        for piece in [*resampler.resample(frame), *resampler.resample(None)]:
            out.mux(stream.encode(piece))
        out.mux(stream.encode(None))
    return path


@pytest.fixture
def tone(tmp_path):
    return write_tone(tmp_path / "tone.wav")


@pytest.mark.parametrize("key", list(FORMATS))
def test_every_format_round_trips(tone, tmp_path, key):
    fmt = FORMATS[key]
    out = convert(tone, tmp_path / f"out.{fmt.extension}", fmt)
    info = probe(out)
    assert info.channels == 2
    assert abs(info.duration - SECONDS) < 0.1
    assert not list(tmp_path.glob("*.part"))


def test_sample_rate_and_channels(tone, tmp_path):
    out = convert(tone, tmp_path / "speech.mp3", FORMATS["mp3"], sample_rate=16000, channels=1)
    info = probe(out)
    assert (info.sample_rate, info.channels) == (16000, 1)


def test_opus_rate_is_snapped_to_what_the_encoder_accepts(tone, tmp_path):
    assert pick_rate("libopus", 44100) == 48000
    out = convert(tone, tmp_path / "x.opus", FORMATS["opus"], sample_rate=44100)
    assert probe(out).sample_rate == 48000


def test_bitrate_changes_file_size(tone, tmp_path):
    low = convert(tone, tmp_path / "low.mp3", FORMATS["mp3"], bitrate=128)
    high = convert(tone, tmp_path / "high.mp3", FORMATS["mp3"], bitrate=320)
    assert high.stat().st_size > low.stat().st_size * 2


def test_tags_are_kept(tmp_path):
    src = write_tone(tmp_path / "song.m4a", codec="aac", fmt="ipod", title="Kanto")
    out = convert(src, tmp_path / "song.mp3", FORMATS["mp3"])
    with av.open(str(out)) as container:
        assert container.metadata.get("title") == "Kanto"


def test_audio_from_a_video_container(tmp_path):
    src = write_tone(tmp_path / "clip.mp4", codec="aac", fmt="mp4")
    out = convert(src, tmp_path / "clip.mp3", FORMATS["mp3"])
    assert abs(probe(out).duration - SECONDS) < 0.1


def test_progress_reaches_the_end(tone, tmp_path):
    seen = []
    convert(
        tone, tmp_path / "p.flac", FORMATS["flac"], on_progress=lambda d, t: seen.append((d, t))
    )
    done = [d for d, _ in seen]
    assert done == sorted(done)
    assert seen[-1][1] == 2000 and seen[-1][0] > 1900


def test_cancel_leaves_no_file(tone, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        convert(tone, tmp_path / "c.mp3", FORMATS["mp3"], cancel=token)
    assert not list(tmp_path.glob("c.mp3*"))


def test_broken_input_fails_cleanly_in_a_batch(tone, tmp_path):
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio at all" * 100)
    out_dir = tmp_path / "out"
    work = make_audio_convert_job(out_dir, ConflictPolicy.RENAME, "m4a")
    report = run_batch([bad, tone], work)
    assert len(report.failed) == 1 and len(report.succeeded) == 1
    assert sorted(p.name for p in out_dir.iterdir()) == ["tone.m4a"]


# --------------------------------------------------------------------- UI


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_convert_tool_end_to_end(app, tone, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from mediakit.modules.audio.hub import build_audio_hub

    hub = build_audio_hub()
    hub.show()
    hub.open_tool("convert")
    tool = hub.current_tool()
    tool.add_paths([tone])
    app.processEvents()
    assert "PCM_S16LE" in tool.info_label.text() and "0:02" in tool.info_label.text()

    flac = tool.format_tiles[3]
    flac.click()
    assert tool.bitrate_combo.isHidden()  # lossless: nothing to choose
    tool.format_tiles[0].click()  # mp3
    assert not tool.bitrate_combo.isHidden()
    assert "kB" in tool.info_label.text()  # size estimate shown

    tool._out_dir = tmp_path / "out"
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not tool.is_running() else None)
    tool.run_btn.click()
    timer.start(30)
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    assert probe(tmp_path / "out" / "tone.mp3").codec.startswith("mp3")
    hub.close()
