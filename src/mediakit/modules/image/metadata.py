"""Inspect and remove image metadata. Pure domain logic, no Qt.

Stripping is done at the container level (JPEG markers, PNG chunks,
WebP RIFF chunks), never by decoding and re-encoding the pixels:
  - lossless: a JPEG is not re-compressed,
  - fast: only the file structure is copied.

Kept on purpose:
  - orientation: written back as a tiny EXIF block, otherwise phone
    photos would turn sideways once the original EXIF is gone,
  - colour profile (ICC), optional: removing it can shift colours.
Removed: EXIF (GPS, camera, dates, serial numbers), XMP, IPTC,
comments, PNG text chunks and timestamps.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy, resolve_output_path
from mediakit.modules.image.convert import convert_image
from mediakit.modules.image.ops import auto_orient

# EXIF tag ids
_ORIENTATION = 0x0112
_MAKE, _MODEL, _SOFTWARE = 0x010F, 0x0110, 0x0131
_DATETIME = 0x0132
_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003


@dataclass
class MetadataReport:
    """What a file carries, in user terms."""

    has_gps: bool = False
    camera: str = ""
    taken: str = ""
    software: str = ""
    has_xmp: bool = False
    has_iptc: bool = False
    has_comment: bool = False
    has_icc: bool = False
    other: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (
            self.has_gps
            or self.camera
            or self.taken
            or self.software
            or self.has_xmp
            or self.has_iptc
            or self.has_comment
            or self.other
        )


def inspect_metadata(path: Path) -> MetadataReport:
    report = MetadataReport()
    with Image.open(path) as image:
        exif = image.getexif()
        info = image.info
        if exif:
            gps = exif.get_ifd(_GPS_IFD)
            report.has_gps = bool(gps)
            make = str(exif.get(_MAKE, "")).strip("\x00 ")
            model = str(exif.get(_MODEL, "")).strip("\x00 ")
            report.camera = " ".join(part for part in (make, model) if part)
            details = exif.get_ifd(_EXIF_IFD)
            taken = details.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME, "")
            report.taken = str(taken).strip("\x00 ")
            report.software = str(exif.get(_SOFTWARE, "")).strip("\x00 ")
        report.has_xmp = bool(info.get("xmp") or info.get("XML:com.adobe.xmp"))
        report.has_iptc = "photoshop" in info or "iptc" in info
        report.has_comment = bool(info.get("comment"))
        report.has_icc = bool(info.get("icc_profile"))
        text_keys = [
            key
            for key in info
            if key
            not in {
                "icc_profile",
                "exif",
                "xmp",
                "XML:com.adobe.xmp",
                "comment",
                "photoshop",
                "dpi",
                "jfif",
                "jfif_version",
                "jfif_unit",
                "jfif_density",
                "progressive",
                "progression",
                "adobe",
                "adobe_transform",
                "transparency",
                "gamma",
                "srgb",
                "loop",
                "duration",
                "background",
                "aspect",
                "compression",
                "lossless",
            }
        ]
        report.other = sorted(text_keys)
    return report


def _orientation_of(path: Path) -> int:
    with Image.open(path) as image:
        return int(image.getexif().get(_ORIENTATION, 1) or 1)


def _orientation_exif(orientation: int) -> bytes:
    """Smallest valid EXIF block that carries only the orientation."""
    exif = Image.Exif()
    exif[_ORIENTATION] = orientation
    return exif.tobytes()  # starts with b"Exif\0\0"


# ------------------------------------------------------------------ JPEG


def _strip_jpeg(data: bytes, keep_icc: bool, orientation: int) -> bytes:
    if data[:2] != b"\xff\xd8":
        raise ValueError("Not a JPEG file")
    out = bytearray(b"\xff\xd8")
    pos = 2
    # EXIF belongs right after SOI, or right after APP0 (JFIF) if the
    # file has one. Without APP0, insert it immediately.
    inserted_exif = False
    if orientation != 1 and data[2:4] != b"\xff\xe0":
        out += _app1(_orientation_exif(orientation))
        inserted_exif = True
    while pos < len(data):
        if data[pos] != 0xFF:
            raise ValueError("Corrupt JPEG marker stream")
        marker = data[pos + 1]
        # Fill bytes (0xFF 0xFF ...) are allowed between markers.
        if marker == 0xFF:
            pos += 1
            continue
        # Start of scan: the rest is compressed image data, copy as is.
        if marker == 0xDA:
            out += data[pos:]
            return bytes(out)
        # Markers without a length field.
        if marker in (0x01, *range(0xD0, 0xD8)):
            out += data[pos : pos + 2]
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        segment = data[pos : pos + 2 + length]
        payload = segment[4:]
        pos += 2 + length

        drop = False
        if marker == 0xE1 or marker == 0xED or marker == 0xFE:  # APP1: EXIF or XMP
            drop = True
        elif marker == 0xE2 and payload.startswith(b"ICC_PROFILE\0"):
            drop = not keep_icc
        elif 0xE3 <= marker <= 0xEF and marker != 0xEE:
            # APP3..APP15 except APP14 (Adobe colour transform, needed
            # to decode some CMYK JPEGs): vendor data, maker notes.
            drop = True

        if not drop:
            out += segment
            # Put the orientation EXIF right after APP0 (JFIF), where
            # readers expect EXIF to be.
            if marker == 0xE0 and orientation != 1 and not inserted_exif:
                out += _app1(_orientation_exif(orientation))
                inserted_exif = True
    raise ValueError("JPEG has no image data")


def _app1(payload: bytes) -> bytes:
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


# ------------------------------------------------------------------- PNG

# Chunks needed to render the image correctly. Everything else
# (tEXt, zTXt, iTXt, eXIf, tIME, unknown private chunks) is dropped.
_PNG_KEEP = {
    b"IHDR",
    b"PLTE",
    b"IDAT",
    b"IEND",
    b"tRNS",
    b"gAMA",
    b"cHRM",
    b"sRGB",
    b"sBIT",
    b"bKGD",
    b"pHYs",
    b"acTL",
    b"fcTL",
    b"fdAT",
}


def _strip_png(data: bytes, keep_icc: bool) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("Not a PNG file")
    out = bytearray(signature)
    pos = len(signature)
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length  # length + type + data + crc
        if kind in _PNG_KEEP or (kind == b"iCCP" and keep_icc):
            out += data[pos:end]  # copied with its own CRC
        pos = end
        if kind == b"IEND":
            break
    return bytes(out)


# ------------------------------------------------------------------ WebP


def _strip_webp(data: bytes, keep_icc: bool) -> bytes:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Not a WebP file")
    chunks = []
    pos = 12
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        padded = size + (size & 1)  # RIFF chunks are 2-byte aligned
        chunks.append((kind, data[pos : pos + 8 + padded]))
        pos += 8 + padded

    out = bytearray()
    for kind, chunk in chunks:
        if kind in (b"EXIF", b"XMP "):
            continue
        if kind == b"ICCP" and not keep_icc:
            continue
        if kind == b"VP8X":
            # Flags byte: bit 5 ICC, bit 3 EXIF, bit 2 XMP. Clear what
            # we removed or decoders will look for missing chunks.
            flags = chunk[8]
            flags &= ~0b00001100
            if not keep_icc:
                flags &= ~0b00100000
            chunk = chunk[:8] + bytes([flags]) + chunk[9:]
        out += chunk
    return b"RIFF" + struct.pack("<I", len(out) + 4) + b"WEBP" + bytes(out)


# ----------------------------------------------------------------- entry

LOSSLESS_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def strip_metadata(source: Path, destination: Path, keep_icc: bool = True) -> Path:
    """Write a copy of `source` without metadata.

    JPEG/PNG/WebP are handled losslessly. Other formats are re-saved by
    Pillow (which does not carry metadata over) as PNG by the caller.
    """
    ext = source.suffix.lower().lstrip(".")
    data = source.read_bytes()
    if ext in ("jpg", "jpeg"):
        cleaned = _strip_jpeg(data, keep_icc, _orientation_of(source))
    elif ext == "png":
        cleaned = _strip_png(data, keep_icc)
    elif ext == "webp":
        cleaned = _strip_webp(data, keep_icc)
    else:
        raise ValueError(f"Lossless stripping not supported for .{ext}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(cleaned)
    return destination


def make_strip_job(
    out_dir: Path | None,
    policy: ConflictPolicy = ConflictPolicy.RENAME,
    keep_icc: bool = True,
) -> WorkFn:
    """Batch job: lossless strip for JPEG/PNG/WebP, PNG re-save otherwise.

    The fallback is still metadata-free (Pillow does not copy EXIF on
    save) and lossless (PNG), it just can't keep the original format.
    """

    def work(source: Path) -> Path | None:
        ext = source.suffix.lower().lstrip(".")
        lossless = ext in LOSSLESS_EXTENSIONS
        target_ext = ("jpg" if ext == "jpeg" else ext) if lossless else "png"
        directory = out_dir if out_dir is not None else source.parent
        destination = resolve_output_path(source, directory, target_ext, policy, "_clean")
        if destination is None:
            return None
        if lossless:
            return strip_metadata(source, destination, keep_icc=keep_icc)
        return convert_image(source, destination, transforms=[auto_orient])

    return work
