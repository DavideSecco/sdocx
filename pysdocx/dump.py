"""Raw-byte inspection helpers."""

import zipfile
from pathlib import Path

PURPOSES = {
    "pageIdInfo.dat": "Page UUID registry",
    ".page": "Stroke data (geometry + attributes)",
    "mediaInfo.dat": "Media file manifest",
    ".spi": "Page thumbnail (Samsung proprietary)",
    "note.note": "Note metadata & settings",
    "end_tag.bin": "Document footer & timestamps",
    # media/<index>@... attachments, classified by extension. Sticky-notes and audio are not
    # referenced from any .page object tree (verified empty object trees on a dedicated GT
    # sample) — they're document-level attachments, not per-page placements, at least in the
    # one sample seen so far. Nested .sdocx = a full sticky-memo sub-document (open with
    # pysdocx itself); .m4a = a voice-memo recording.
    ".m4a": "Audio attachment (voice memo)",
    ".jpg": "Imported image",
    ".jpeg": "Imported image",
    ".png": "Imported image",
    "@stickymemo": "Nested sticky-memo (embedded .sdocx sub-document)",
    ".sdocx": "Nested embedded .sdocx sub-document",  # fallback for naming schemes other than stickymemo_*
}


def hexdump(data: bytes, offset: int = 0, limit: int = 0) -> str:
    """Format binary data as an annotated hex dump."""
    lines = []
    n = len(data) if limit == 0 else min(len(data), limit)
    for i in range(0, n, 16):
        chunk = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "·" for b in chunk)
        lines.append(f"  {offset + i:04x}  {hex_part:<48s} {ascii_part}")
    if limit and len(data) > limit:
        lines.append(f"  ... ({len(data) - limit} more bytes)")
    return "\n".join(lines)


def dump_container(path: Path) -> str:
    """List a .sdocx archive's contents with size, compression ratio, and purpose."""
    lines = [f"{'File':<45} {'Size':>10}  {'Ratio':>6}  Purpose", "─" * 90]
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            ratio = (
                f"{(1 - info.compress_size / info.file_size) * 100:.0f}%"
                if info.file_size
                else "—"
            )
            purpose = next((v for k, v in PURPOSES.items() if k in info.filename), "?")
            lines.append(f"{info.filename:<45} {info.file_size:>10,}  {ratio:>6}  {purpose}")
    return "\n".join(lines)
