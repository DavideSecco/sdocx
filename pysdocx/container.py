"""ZIP container access: listing .page files and the note-level background color."""

import zipfile
from pathlib import Path

BG_COLOR_DEFAULT = "#ffffff"


def list_pages(path: Path) -> list[str]:
    """Return the archive's .page filenames in true document page order.

    NOT sorted by UUID — that scrambles the order (e.g. on the benchmark it
    puts logical page 4 first). The authoritative order is the UUID list in
    `pageIdInfo.dat` (UTF-16LE), which matches the zip's insertion order; we
    use `pageIdInfo.dat` when present and fall back to insertion order.
    """
    with zipfile.ZipFile(path) as z:
        zip_order = [i.filename for i in z.infolist() if i.filename.endswith(".page")]
        if "pageIdInfo.dat" not in z.namelist():
            return zip_order
        uuid_order = _page_uuid_order(z.read("pageIdInfo.dat"))
        by_uuid = {name.removesuffix(".page"): name for name in zip_order}
        ordered = [by_uuid[u] for u in uuid_order if u in by_uuid]
        # Append any page not referenced by pageIdInfo (shouldn't happen) so
        # nothing is silently dropped.
        ordered += [name for name in zip_order if name not in ordered]
        return ordered


def _page_uuid_order(page_id_info: bytes) -> list[str]:
    """Extract the ordered page-UUID list from pageIdInfo.dat (UTF-16LE UUIDs)."""
    import re

    text = page_id_info.decode("utf-16-le", errors="replace")
    pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    return re.findall(pattern, text)


def load_page(path: Path, page_filename: str | None = None) -> tuple[str, bytes]:
    """Read one .page file's bytes. Defaults to the first page in the archive."""
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if i.filename.endswith(".page")]
        if not names:
            raise ValueError(f"{path}: no .page file in archive")
        key = page_filename or names[0]
        return key, z.read(key)


def load_media_by_index(path: Path, index: int) -> tuple[str, bytes] | None:
    """Load a media file by its archive index (the `<index>@...` prefix). Returns (name, bytes)."""
    prefix = f"media/{index}@"
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename.startswith(prefix):
                return info.filename, z.read(info.filename)
    return None


def raster_media_indices(path: Path) -> set[int]:
    """Media indices whose file is a jpg/png raster (usable as an image/drawing bitmap)."""
    indices: set[int] = set()
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith("media/") or "@" not in name:
                continue
            head = z.read(name)[:8]
            if head[:3] == b"\xff\xd8\xff" or head[:4] == b"\x89PNG":
                try:
                    indices.add(int(name.split("/")[1].split("@")[0]))
                except ValueError:
                    continue
    return indices


ATTACHMENT_EXT_KIND = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".m4a": "audio",
    ".spi": "thumbnail",
}


def list_attachments(path: Path) -> list[dict]:
    """Enumerate document-level media attachments: images, audio, nested sticky-memos.

    These are not necessarily placed via any `.page` object tree: on a dedicated GT sample
    (`Associationpages&stickynote&images&audio`), the pages meant to host the sticky-notes and
    audio recording have a completely EMPTY object tree (parse_page_tree finds zero objects on
    them) — so unlike images/shapes/drawings, no per-page placement is known for these yet.
    Surfacing them here at least makes them visible (`kind`, `size`) instead of silently absent
    from any render. Returns `[{index, name, kind, size}]`, `kind` in
    `{"image", "audio", "sticky_note", "thumbnail", "other"}`.
    """
    attachments: list[dict] = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith("media/") or "@" not in name:
                continue
            try:
                index = int(name.split("/")[1].split("@")[0])
            except ValueError:
                continue
            lower = name.lower()
            if "@stickymemo" in lower or lower.endswith(".sdocx"):
                kind = "sticky_note"
            else:
                kind = next(
                    (k for ext, k in ATTACHMENT_EXT_KIND.items() if lower.endswith(ext)),
                    "other",
                )
            attachments.append({"index": index, "name": name, "kind": kind, "size": info.file_size})
    return attachments


def load_note(path: Path) -> bytes | None:
    """Read the container's note.note (document metadata + typed rich text), or None if absent."""
    with zipfile.ZipFile(path) as z:
        if "note.note" not in z.namelist():
            return None
        return z.read("note.note")


def bg_color_from_note(note: bytes) -> str:
    """Scan note.note bytes for the background-color TLV record: [18 00] [00 00 01 00 00 00] [R][G][B][FF]."""
    for i in range(len(note) - 12):
        if (
            note[i] == 0x18
            and note[i + 1] == 0x00
            and note[i + 2 : i + 8] == b"\x00\x00\x01\x00\x00\x00"
            and note[i + 11] == 0xFF
        ):
            r, g, b = note[i + 8], note[i + 9], note[i + 10]
            return f"#{r:02x}{g:02x}{b:02x}"
    return BG_COLOR_DEFAULT


def load_bg_color(path: Path) -> str:
    """Read note.note from the archive and extract its background color."""
    with zipfile.ZipFile(path) as z:
        if "note.note" not in z.namelist():
            return BG_COLOR_DEFAULT
        return bg_color_from_note(z.read("note.note"))


def load_page_with_bg(path: Path, page_filename: str | None = None) -> tuple[str, bytes, str]:
    """Read one .page file's bytes plus the note's background color."""
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if i.filename.endswith(".page")]
        if not names:
            raise ValueError(f"{path}: no .page file in archive")
        key = page_filename or names[0]
        bg_color = bg_color_from_note(z.read("note.note")) if "note.note" in z.namelist() else BG_COLOR_DEFAULT
        return key, z.read(key), bg_color
