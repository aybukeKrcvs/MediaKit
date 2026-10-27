"""Audio & speech module entry point. Tools arrive in Phase 2."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from mediakit.ui.tool_hub import ToolHub, ToolSpec


def audio_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            "convert",
            "audio_convert",
            lambda: QCoreApplication.translate("AudioTools", "Convert audio"),
            lambda: QCoreApplication.translate("AudioTools", "MP3, WAV, FLAC, OGG, M4A and more."),
        ),
        ToolSpec(
            "transcribe",
            "transcribe",
            lambda: QCoreApplication.translate("AudioTools", "Speech to text"),
            lambda: QCoreApplication.translate(
                "AudioTools", "Transcribe recordings, export SRT/VTT subtitles."
            ),
        ),
        ToolSpec(
            "denoise",
            "denoise",
            lambda: QCoreApplication.translate("AudioTools", "Reduce noise"),
            lambda: QCoreApplication.translate("AudioTools", "Clean up hiss and background noise."),
        ),
        ToolSpec(
            "tts",
            "tts",
            lambda: QCoreApplication.translate("AudioTools", "Text to speech"),
            lambda: QCoreApplication.translate(
                "AudioTools", "Read text aloud in Turkish or English."
            ),
        ),
        ToolSpec(
            "record",
            "record",
            lambda: QCoreApplication.translate("AudioTools", "Record & transcribe"),
            lambda: QCoreApplication.translate(
                "AudioTools", "Record from the microphone, then transcribe."
            ),
        ),
    ]


def build_audio_hub() -> ToolHub:
    return ToolHub(
        lambda: QCoreApplication.translate("AudioTools", "AUDIO & SPEECH"),
        lambda: QCoreApplication.translate(
            "AudioTools", "Pick a task. Everything runs offline on this computer."
        ),
        audio_tool_specs(),
    )
