"""PDF module entry point. Tools arrive in Phase 3."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from mediakit.ui.tool_hub import ToolHub, ToolSpec


def pdf_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            "merge",
            "pdf_merge",
            lambda: QCoreApplication.translate("PdfTools", "Merge PDF"),
            lambda: QCoreApplication.translate(
                "PdfTools", "Combine several PDFs in the order you choose."
            ),
        ),
        ToolSpec(
            "split",
            "pdf_split",
            lambda: QCoreApplication.translate("PdfTools", "Split PDF"),
            lambda: QCoreApplication.translate(
                "PdfTools", "Extract pages or ranges into separate files."
            ),
        ),
        ToolSpec(
            "pages",
            "pdf_pages",
            lambda: QCoreApplication.translate("PdfTools", "Organize pages"),
            lambda: QCoreApplication.translate("PdfTools", "Rotate, reorder or delete pages."),
        ),
        ToolSpec(
            "compress",
            "pdf_compress",
            lambda: QCoreApplication.translate("PdfTools", "Compress PDF"),
            lambda: QCoreApplication.translate("PdfTools", "Reduce file size for sharing."),
        ),
        ToolSpec(
            "from_pdf",
            "pdf_from",
            lambda: QCoreApplication.translate("PdfTools", "Convert from PDF"),
            lambda: QCoreApplication.translate(
                "PdfTools", "PDF to images, text, Markdown, Word or Excel."
            ),
        ),
        ToolSpec(
            "to_pdf",
            "pdf_to",
            lambda: QCoreApplication.translate("PdfTools", "Convert to PDF"),
            lambda: QCoreApplication.translate(
                "PdfTools", "Images, Markdown, HTML or Office files to PDF."
            ),
        ),
        ToolSpec(
            "stamp",
            "pdf_stamp",
            lambda: QCoreApplication.translate("PdfTools", "Watermark & page numbers"),
            lambda: QCoreApplication.translate("PdfTools", "Stamp text, a logo or page numbers."),
        ),
        ToolSpec(
            "protect",
            "lock",
            lambda: QCoreApplication.translate("PdfTools", "Protect & clean"),
            lambda: QCoreApplication.translate(
                "PdfTools", "Add or remove a password, strip metadata."
            ),
        ),
    ]


def build_pdf_hub() -> ToolHub:
    return ToolHub(
        lambda: QCoreApplication.translate("PdfTools", "PDF TOOLS"),
        lambda: QCoreApplication.translate(
            "PdfTools", "Pick a task. Everything runs offline on this computer."
        ),
        pdf_tool_specs(),
    )
