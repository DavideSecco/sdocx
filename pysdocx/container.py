"""ZIP container access: listing pages, media, and note-level metadata."""

import hashlib
import struct
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

    parsed = parse_page_id_info(page_id_info)
    if parsed is not None and parsed["records"]:
        return [record["uuid"] for record in parsed["records"]]
    text = page_id_info.decode("utf-16-le", errors="replace")
    pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    return re.findall(pattern, text)


PAGE_ID_INFO_RECORD_SIZE = 0x6A
PAGE_ID_INFO_UUID_CHARS = 36


def parse_page_id_info(data: bytes) -> dict | None:
    """Parse `pageIdInfo.dat` page order plus opaque page hashes.

    Layout observed corpus-wide:
    `32-byte document head`, `u16 page_count`, then `page_count` records of 0x6a bytes:
    `u16(36)`, UTF-16LE page UUID, 32-byte per-page hash. The per-page hashes are stable
    manifest data but do not match raw SHA-256 of the `.page` members in the current corpus.
    """
    if len(data) < 34:
        return None
    page_count = struct.unpack_from("<H", data, 0x20)[0]
    off = 0x22
    records = []
    try:
        for _ in range(page_count):
            end = off + PAGE_ID_INFO_RECORD_SIZE
            if end > len(data):
                return None
            uuid_chars = struct.unpack_from("<H", data, off)[0]
            uuid_start = off + 2
            uuid_end = uuid_start + uuid_chars * 2
            if uuid_chars != PAGE_ID_INFO_UUID_CHARS or uuid_end + 32 > end:
                return None
            uuid = data[uuid_start:uuid_end].decode("utf-16-le")
            records.append({
                "off": off,
                "end": end,
                "uuid_chars": uuid_chars,
                "uuid": uuid,
                "page_hash": data[uuid_end : uuid_end + 32].hex(),
                "raw_tail_hex": data[uuid_end + 32 : end].hex(),
            })
            off = end
    except (UnicodeDecodeError, struct.error):
        return None
    return {
        "head_hash": data[:0x20].hex(),
        "page_count": page_count,
        "records": records,
        "end": off,
        "trailing_hex": data[off:].hex(),
        "valid_size": off == len(data),
    }


def list_page_id_info(path: Path) -> dict | None:
    """Load and parse `pageIdInfo.dat`."""
    data = load_page_id_info(path)
    if data is None:
        return None
    return parse_page_id_info(data)


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


MEDIA_INFO_EOF = b"EOFX"
END_TAG_SIGNATURE = b"Document for S-Pen SDK"
END_TAG_FOOTER_PATTERN = b"\x02\x00\x00\x00\x02\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff"


def load_media_info(path: Path) -> bytes | None:
    """Read `media/mediaInfo.dat`, or None if absent."""
    with zipfile.ZipFile(path) as z:
        if "media/mediaInfo.dat" not in z.namelist():
            return None
        return z.read("media/mediaInfo.dat")


def parse_media_info(data: bytes) -> dict | None:
    """Parse Samsung's media manifest.

    The manifest is:
    `[u32 format_version][u16 count]` followed by `count` records and the ASCII trailer `EOFX`.
    Each record starts with `u32 payload_size`, where the payload excludes that size field:
    `[u32 media_index][u16 filename_chars][UTF-16LE filename][64 ASCII SHA-256 hex][tail]`.
    The filename already includes the `<index>@...` prefix used under `media/`.
    """
    if len(data) < 10:
        return None
    format_version = struct.unpack_from("<I", data, 0)[0]
    count = struct.unpack_from("<H", data, 4)[0]
    off = 6
    records = []
    try:
        for _ in range(count):
            if off + 10 > len(data):
                return None
            payload_size = struct.unpack_from("<I", data, off)[0]
            end = off + 4 + payload_size
            if end > len(data):
                return None
            media_index = struct.unpack_from("<I", data, off + 4)[0]
            name_chars = struct.unpack_from("<H", data, off + 8)[0]
            name_start = off + 10
            name_end = name_start + name_chars * 2
            digest_end = name_end + 64
            if digest_end > end:
                return None
            name = data[name_start:name_end].decode("utf-16-le")
            sha256 = data[name_end:digest_end].decode("ascii")
            raw_tail = data[digest_end:end]
            ref_count = struct.unpack_from("<H", raw_tail, 0)[0] if len(raw_tail) >= 2 else None
            modified_time = (
                struct.unpack_from("<Q", raw_tail, 2)[0]
                if len(raw_tail) >= 10
                else None
            )
            is_attached = bool(raw_tail[10]) if len(raw_tail) >= 11 else None
            records.append({
                "off": off,
                "end": end,
                "payload_size": payload_size,
                "media_index": media_index,
                "name": name,
                "archive_name": f"media/{name}",
                "name_chars": name_chars,
                "sha256": sha256,
                "raw_tail": raw_tail.hex(),
                "ref_count": ref_count,
                "modified_time": modified_time,
                "is_attached": is_attached,
                # Back-compat aliases for older diagnostics and tests.
                "tail_tag": ref_count,
                "time_candidate": modified_time,
                "tail_marker": int(is_attached) if is_attached is not None else None,
            })
            off = end
    except (UnicodeDecodeError, struct.error):
        return None

    return {
        "format_version": format_version,
        # Back-compat alias for older diagnostics and tests.
        "magic": format_version,
        "count": count,
        "records": records,
        "eof_off": off,
        "eof": data[off : off + len(MEDIA_INFO_EOF)].decode("ascii", errors="replace"),
        "valid_eof": data[off : off + len(MEDIA_INFO_EOF)] == MEDIA_INFO_EOF and off + 4 == len(data),
    }


def list_media_info(path: Path, verify_hash: bool = False) -> dict | None:
    """Load and optionally verify `media/mediaInfo.dat` against archive members."""
    with zipfile.ZipFile(path) as z:
        if "media/mediaInfo.dat" not in z.namelist():
            return None
        parsed = parse_media_info(z.read("media/mediaInfo.dat"))
        if parsed is None:
            return None
        infos = {info.filename: info for info in z.infolist()}
        records = []
        for record in parsed["records"]:
            rec = dict(record)
            info = infos.get(rec["archive_name"])
            rec["exists"] = info is not None
            rec["zip_size"] = info.file_size if info else None
            rec["index_matches_name"] = rec["name"].startswith(f"{rec['media_index']}@")
            if verify_hash and info is not None:
                rec["sha256_matches"] = hashlib.sha256(z.read(rec["archive_name"])).hexdigest() == rec["sha256"]
            records.append(rec)
        parsed = dict(parsed)
        parsed["records"] = records
        manifest_names = {record["archive_name"] for record in records}
        parsed["unlisted_media"] = sorted(
            name
            for name in infos
            if name.startswith("media/") and name != "media/mediaInfo.dat" and name not in manifest_names
        )
        return parsed


def load_end_tag(path: Path) -> bytes | None:
    """Read `end_tag.bin`, or None if absent."""
    with zipfile.ZipFile(path) as z:
        if "end_tag.bin" not in z.namelist():
            return None
        return z.read("end_tag.bin")


def _read_short_u16_string(data: bytes, off: int) -> tuple[str, int] | None:
    if off + 2 > len(data):
        return None
    n_chars = struct.unpack_from("<H", data, off)[0]
    start = off + 2
    end = start + n_chars * 2
    if end > len(data):
        return None
    try:
        return data[start:end].decode("utf-16-le"), end
    except UnicodeDecodeError:
        return None


def _read_long_u16_string_before(data: bytes, off: int, limit: int) -> tuple[str, int] | None:
    if off + 4 > limit:
        return None
    n_chars = struct.unpack_from("<I", data, off)[0]
    start = off + 4
    end = start + n_chars * 2
    if end > limit:
        return None
    try:
        return data[start:end].decode("utf-16-le"), end
    except UnicodeDecodeError:
        return None


def parse_end_tag(data: bytes) -> dict | None:
    """Parse the fixed footer record stored in `end_tag.bin`.

    Stable corpus fields: the first u16 is the byte count after that size field; the next u32
    matches note format version; offset +8 is the note modified time; the tail carries the SDK
    display timestamps, fixed text/theme settings, server checkpoint, orientation, optional custom
    data, then `Document for S-Pen SDK`.
    """
    if len(data) < 96:
        return None
    signature_off = data.find(END_TAG_SIGNATURE)
    if signature_off < 0:
        return None
    try:
        payload_size = struct.unpack_from("<H", data, 0)[0]
        format_version = struct.unpack_from("<I", data, 2)[0]
        note_uuid_result = _read_short_u16_string(data, 6)
        if note_uuid_result is None:
            return None
        note_uuid, off = note_uuid_result
        modified_time = struct.unpack_from("<q", data, 8)[0]
        property_flags = struct.unpack_from("<I", data, 16)[0]
        cover_image_result = _read_short_u16_string(data, 20)
        if cover_image_result is None:
            return None
        cover_image, off = cover_image_result
        page_width = struct.unpack_from("<H", data, 22)[0]
        note_width = struct.unpack_from("<I", data, 22)[0]
        document_height = struct.unpack_from("<f", data, 26)[0]
        app_name_result = _read_short_u16_string(data, 30)
        if app_name_result is None:
            return None
        app_name, off = app_name_result
        app_version_major = struct.unpack_from("<I", data, off)[0]
        app_version_minor = struct.unpack_from("<I", data, off + 4)[0]
        patch_name_result = _read_short_u16_string(data, off + 8)
        if patch_name_result is None:
            return None
        app_version_patch_name, off = patch_name_result
        min_format_version = struct.unpack_from("<I", data, off)[0]
        format_version_dup = min_format_version
        off += 4
        created_time_header = struct.unpack_from("<q", data, 46)[0]
        off += 8
        last_viewed_page_index = struct.unpack_from("<I", data, off)[0]
        page_model = struct.unpack_from("<H", data, off + 4)[0]
        document_type = struct.unpack_from("<H", data, off + 6)[0]
        owner_id_result = _read_short_u16_string(data, off + 8)
        if owner_id_result is None:
            return None
        owner_id, off = owner_id_result
        skipped_size = struct.unpack_from("<I", data, off)[0]
        off += 4 + skipped_size
        encryption_data_size = struct.unpack_from("<I", data, off)[0]
        off += 4 + encryption_data_size
        display_created_time = struct.unpack_from("<q", data, off)[0]
        display_modified_time = struct.unpack_from("<q", data, off + 8)[0]
        last_recognised_data_modified_time = struct.unpack_from("<q", data, off + 16)[0]
        off += 24
        fixed_font_result = _read_short_u16_string(data, off)
        if fixed_font_result is None:
            return None
        fixed_font, off = fixed_font_result
        fixed_text_direction = struct.unpack_from("<I", data, off)[0]
        fixed_background_theme = struct.unpack_from("<I", data, off + 4)[0]
        server_checkpoint = struct.unpack_from("<q", data, off + 8)[0]
        new_orientation = struct.unpack_from("<I", data, off + 16)[0]
        min_unknown_version = struct.unpack_from("<I", data, off + 20)[0]
        off += 24
        app_custom_data = ""
        if off < signature_off:
            custom_result = _read_long_u16_string_before(data, off, signature_off)
            if custom_result is None:
                return None
            app_custom_data, off = custom_result
    except struct.error:
        return None
    footer_off = data.rfind(END_TAG_FOOTER_PATTERN, 0, signature_off)
    footer_a = footer_b = None
    footer_sentinel = None
    if footer_off >= 0:
        footer_a = struct.unpack_from("<I", data, footer_off)[0]
        footer_b = struct.unpack_from("<I", data, footer_off + 4)[0]
        footer_sentinel = struct.unpack_from("<q", data, footer_off + 8)[0]
    return {
        "payload_size": payload_size,
        "format_version": format_version,
        "note_uuid": note_uuid,
        "property_flags": property_flags,
        "is_landscape": bool(property_flags & 0x2),
        "cover_image": cover_image,
        "format_version_dup": format_version_dup,
        "modified_time": modified_time,
        "note_width": note_width,
        "page_width": page_width,
        "document_height": document_height,
        "note_height": document_height,
        "app_name": app_name,
        "app_version_major": app_version_major,
        "app_version_minor": app_version_minor,
        "app_version_patch_name": app_version_patch_name,
        "min_format_version": min_format_version,
        "created_time_header": created_time_header,
        "last_viewed_page_index": last_viewed_page_index,
        "page_model": page_model,
        "document_type": document_type,
        "owner_id": owner_id,
        "skipped_size": skipped_size,
        "encryption_data_size": encryption_data_size,
        "display_created_time": display_created_time,
        "display_modified_time": display_modified_time,
        "last_recognised_data_modified_time": last_recognised_data_modified_time,
        # Back-compat aliases for older diagnostics and tests.
        "created_time_a": display_created_time,
        "created_time_b": display_modified_time,
        "extra_time_candidate": last_recognised_data_modified_time,
        "fixed_font": fixed_font,
        "fixed_text_direction": fixed_text_direction,
        "fixed_background_theme": fixed_background_theme,
        "server_checkpoint": server_checkpoint,
        "new_orientation": new_orientation,
        "min_unknown_version": min_unknown_version,
        "app_custom_data": app_custom_data,
        "sdk_struct_end_off": off,
        "footer_u32": [footer_a, footer_b],
        "footer_sentinel": footer_sentinel,
        "footer_off": footer_off,
        "signature_off": signature_off,
        "signature": data[signature_off:].decode("ascii", errors="replace"),
        "valid_size": payload_size == len(data) - 2,
        "valid_signature": data[signature_off:] == END_TAG_SIGNATURE,
        "raw_mid_hex": data[16:72].hex(),
        "raw_between_times_and_footer_hex": data[88:max(88, footer_off)].hex() if footer_off >= 0 else data[88:signature_off].hex(),
        "raw_footer_padding_hex": data[footer_off + 16:signature_off].hex() if footer_off >= 0 else "",
    }


def list_end_tag(path: Path) -> dict | None:
    """Load and parse `end_tag.bin`."""
    data = load_end_tag(path)
    if data is None:
        return None
    return parse_end_tag(data)


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
    media_info = list_media_info(path, verify_hash=False)
    manifest_by_name = {
        record["archive_name"]: record
        for record in (media_info or {}).get("records", ())
    }
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
            manifest = manifest_by_name.get(name, {})
            attachments.append({
                "index": index,
                "name": name,
                "kind": kind,
                "size": info.file_size,
                "sha256": manifest.get("sha256"),
                "media_info_ref_count": manifest.get("ref_count"),
                "media_info_modified_time": manifest.get("modified_time"),
            })
    return attachments


def load_note(path: Path) -> bytes | None:
    """Read the container's note.note (document metadata + typed rich text), or None if absent."""
    with zipfile.ZipFile(path) as z:
        if "note.note" not in z.namelist():
            return None
        return z.read("note.note")


def load_page_id_info(path: Path) -> bytes | None:
    """Read `pageIdInfo.dat`, or None if absent."""
    with zipfile.ZipFile(path) as z:
        if "pageIdInfo.dat" not in z.namelist():
            return None
        return z.read("pageIdInfo.dat")


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
