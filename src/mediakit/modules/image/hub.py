"""Image module entry point: the list of image tools.

Strings use QCoreApplication.translate("ImageTools", ...) literally so
pyside6-lupdate can find them; they are looked up again on every
retranslate, which is what makes live language switching work.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from mediakit.ui.tool_hub import ToolHub, ToolSpec


def _convert():
    from mediakit.modules.image.tools import ConvertTool

    return ConvertTool()


def _resize():
    from mediakit.modules.image.tools import ResizeTool

    return ResizeTool()


def _compress():
    from mediakit.modules.image.tools import CompressTool

    return CompressTool()


def _crop():
    from mediakit.modules.image.crop_tool import CropRotateTool

    return CropRotateTool()


def _metadata():
    from mediakit.modules.image.metadata_tool import MetadataTool

    return MetadataTool()


def _watermark():
    from mediakit.modules.image.watermark_tool import WatermarkTool

    return WatermarkTool()


def _background():
    from mediakit.modules.image.background_tool import BackgroundTool

    return BackgroundTool()


def _upscale():
    from mediakit.modules.image.upscale_tool import UpscaleTool

    return UpscaleTool()


def image_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            "convert",
            "convert",
            lambda: QCoreApplication.translate("ImageTools", "Convert format"),
            lambda: QCoreApplication.translate("ImageTools", "Turn images into PNG, JPG or WebP."),
            _convert,
        ),
        ToolSpec(
            "resize",
            "resize",
            lambda: QCoreApplication.translate("ImageTools", "Resize"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Change dimensions by width, height or percent."
            ),
            _resize,
        ),
        ToolSpec(
            "crop",
            "crop",
            lambda: QCoreApplication.translate("ImageTools", "Crop & rotate"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Crop by hand or to a fixed ratio, rotate 90\u00b0."
            ),
            _crop,
        ),
        ToolSpec(
            "compress",
            "compress",
            lambda: QCoreApplication.translate("ImageTools", "Compress"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Smaller files, same size and format."
            ),
            _compress,
        ),
        ToolSpec(
            "metadata",
            "metadata",
            lambda: QCoreApplication.translate("ImageTools", "Remove metadata"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Strip location, camera and date info (EXIF)."
            ),
            _metadata,
        ),
        ToolSpec(
            "watermark",
            "watermark",
            lambda: QCoreApplication.translate("ImageTools", "Watermark"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Stamp text or a logo on your images."
            ),
            _watermark,
        ),
        ToolSpec(
            "background",
            "background",
            lambda: QCoreApplication.translate("ImageTools", "Remove background"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Cut out the subject with an AI model."
            ),
            _background,
        ),
        ToolSpec(
            "upscale",
            "upscale",
            lambda: QCoreApplication.translate("ImageTools", "Upscale"),
            lambda: QCoreApplication.translate(
                "ImageTools", "Enlarge images with AI super-resolution."
            ),
            _upscale,
        ),
    ]


def build_image_hub() -> ToolHub:
    return ToolHub(
        lambda: QCoreApplication.translate("ImageTools", "IMAGE TOOLS"),
        lambda: QCoreApplication.translate(
            "ImageTools", "Pick a task. Everything runs offline on this computer."
        ),
        image_tool_specs(),
    )
