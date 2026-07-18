"""Diagnostics for sdocx2pdf-derived hypotheses that are not yet promoted.

This intentionally does not change the reference parser's decoded surface. It
checks whether sdocx2pdf-style structures line up with our already-validated
marker scans:

* end_tag variant coverage for the promoted SDK footer fields;
* text_core::Common-like exclusive frames in text-box object blobs;
* text_core::Common-like frames in note title/body bytes;
* u32 media-reference occurrences inside image and painting/drawing blobs.
* audio object / voice-record / mediaInfo linkage.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_end_tag, list_media_info, list_pages, load_note, raster_media_indices  # noqa: E402
from pysdocx.note import _find_text_field, parse_note_metadata, parse_typed_text  # noqa: E402
from pysdocx.note_doc import find_common_frames  # noqa: E402
from pysdocx.page import parse_page  # noqa: E402


def _paths(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")) + sorted(path.glob("*/note.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def _iter_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        yield from _iter_objects(obj["children"])


def _object_by_off(page: dict, object_off: int) -> dict | None:
    for layer in page["layers"]:
        for obj in _iter_objects(layer["objects"]):
            if obj["off"] == object_off:
                return obj
    return None


def _common_text_frame_candidates(blob: bytes, text: str) -> list[dict]:
    """Find `[u32 frame_size][u32 char_count][utf16 text]` frames matching text."""
    candidates = []
    for off in range(0, max(0, len(blob) - 8)):
        frame_size = struct.unpack_from("<I", blob, off)[0]
        if frame_size < 4 or off + 4 + frame_size > len(blob):
            continue
        char_count = struct.unpack_from("<I", blob, off + 4)[0]
        text_end = off + 8 + char_count * 2
        if char_count == 0 or text_end > off + 4 + frame_size:
            continue
        try:
            candidate_text = blob[off + 8 : text_end].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if candidate_text == text:
            candidates.append({
                "rel": off,
                "frame_size": frame_size,
                "char_count": char_count,
                "trailing_bytes_in_frame": off + 4 + frame_size - text_end,
            })
    return candidates


def _text_box_structural_frame(blob: bytes, text: str, format_version: int) -> dict | None:
    """The text box's own `text_core::Common` frame, parsed structurally.

    The frame text keeps the trailing empty-paragraph newlines that the marker
    scan strips, so the match is prefix + trailing-newline-only.
    """
    for frame in find_common_frames(blob, format_version):
        tail = frame["text"][len(text):]
        if frame["text"].startswith(text) and set(tail) <= {"\n"}:
            return frame
    return None


def _text_box_span_agreement(frame: dict, text_box: dict) -> bool:
    """Structural enabled bold/italic/underline spans == the scanned runs.

    Structural spans use raw frame coordinates (trailing newlines included);
    the scan clamps to the visible text, so rebase before comparing.
    """
    visible_len = len(text_box["text"])
    for span_type, style in ((5, "bold"), (6, "italic"), (7, "underline")):
        structural = set()
        for span in frame["spans"]:
            if span["span_type"] != span_type or not span["extra"].startswith("01"):
                continue
            start, end = span["start"], min(span["end"], visible_len)
            if start < end:
                structural.add((start, end))
        scanned = {
            (run["start"], run["end"])
            for run in text_box.get("runs", ())
            if run["style"] == style
        }
        if structural != scanned:
            return False
    return True


def _u32_offsets(blob: bytes, value: int) -> list[int]:
    return [
        off
        for off in range(0, max(0, len(blob) - 3))
        if struct.unpack_from("<I", blob, off)[0] == value
    ]


def _media_record_by_index(media_info: dict | None) -> dict[int, dict]:
    return {
        record["media_index"]: record
        for record in (media_info or {}).get("records", ())
    }


def _end_tag_variant_row(path: Path) -> dict | None:
    end_tag = list_end_tag(path)
    if end_tag is None:
        return None
    return {
        "file": path.name,
        "page_model": end_tag["page_model"],
        "document_type": end_tag["document_type"],
        "property_flags": end_tag["property_flags"],
        "is_landscape": end_tag["is_landscape"],
        "fixed_text_direction": end_tag["fixed_text_direction"],
        "fixed_background_theme": end_tag["fixed_background_theme"],
        "new_orientation": end_tag["new_orientation"],
        "has_note_uuid": bool(end_tag["note_uuid"]),
        "has_cover_image": bool(end_tag["cover_image"]),
        "has_app_name": bool(end_tag["app_name"]),
        "has_owner_id": bool(end_tag["owner_id"]),
        "has_fixed_font": bool(end_tag["fixed_font"]),
        "has_app_custom_data": bool(end_tag["app_custom_data"]),
        "skipped_size": end_tag["skipped_size"],
        "encryption_data_size": end_tag["encryption_data_size"],
        "sdk_struct_end_matches_signature": end_tag["sdk_struct_end_off"] == end_tag["signature_off"],
    }


def _note_text_rows(path: Path) -> list[dict]:
    note = load_note(path)
    if note is None:
        return []
    rows = []
    meta = parse_note_metadata(note)
    typed = parse_typed_text(note)
    if typed and typed.get("text"):
        for label, text in (("body_text", typed["text"]),):
            candidates = _common_text_frame_candidates(note, text)
            rows.append({
                "file": path.name,
                "surface": label,
                "text_len": len(text),
                "candidate_count": len(candidates),
                "candidates": candidates[:8],
            })
        field = _find_text_field(note)
        if field is not None:
            text_off, raw_text = field
            candidates = _common_text_frame_candidates(note, raw_text)
            rows.append({
                "file": path.name,
                "surface": "body_raw_text_field",
                "text_off": text_off,
                "text_len": len(raw_text),
                "candidate_count": len(candidates),
                "candidates": candidates[:8],
            })
    if meta and meta.get("title_size") and meta.get("title"):
        title_off = meta["title_off"]
        title_blob = note[title_off : title_off + meta["title_size"]]
        candidates = _common_text_frame_candidates(title_blob, meta["title"])
        rows.append({
            "file": path.name,
            "surface": "title_blob",
            "title_off": title_off,
            "text_len": len(meta["title"]),
            "candidate_count": len(candidates),
            "candidates": candidates[:8],
        })
    return rows


def _voice_rows(path: Path, media_info: dict | None, page_object_type_counts: Counter) -> list[dict]:
    note = load_note(path)
    if note is None:
        return []
    meta = parse_note_metadata(note)
    if meta is None:
        return []
    media_by_index = _media_record_by_index(media_info)
    rows = []
    for record in meta.get("tail_records", ()):
        if record.get("kind") != "voice_clip":
            continue
        media_index = record.get("media_index_candidate")
        media_record = media_by_index.get(media_index)
        rows.append({
            "file": path.name,
            "label": record.get("label"),
            "duration": record.get("duration"),
            "duration_ms_display": record.get("duration_ms_display"),
            "actual_duration_ms_candidate": record.get("actual_duration_ms_candidate"),
            "media_index_candidate": media_index,
            "media_record_name": media_record.get("name") if media_record else None,
            "media_record_is_audio": bool(media_record and Path(media_record["name"]).suffix.lower() == ".m4a"),
            "page_audio_object_count": page_object_type_counts.get(10, 0),
        })
    return rows


def collect(paths: list[Path]) -> dict:
    end_tag_rows = []
    note_text_rows = []
    text_rows = []
    media_rows = []
    voice_rows = []
    page_object_type_counts_total = Counter()
    for path in _paths(paths):
        raster_indices = raster_media_indices(path)
        media_info = list_media_info(path, verify_hash=True)
        end_tag_row = _end_tag_variant_row(path)
        if end_tag_row is not None:
            end_tag_rows.append(end_tag_row)
        note_text_rows.extend(_note_text_rows(path))
        note = load_note(path)
        note_meta = parse_note_metadata(note) if note else None
        format_version = (note_meta or {}).get("format_version", 5400)
        page_object_type_counts = Counter()
        with zipfile.ZipFile(path) as z:
            for page_name in list_pages(path):
                data = z.read(page_name)
                page = parse_page(data)
                for layer in page["layers"]:
                    for obj in _iter_objects(layer["objects"]):
                        page_object_type_counts[obj["raw_type"]] += 1
                        page_object_type_counts_total[obj["raw_type"]] += 1
                for text_box in page["text_boxes"]:
                    obj = _object_by_off(page, text_box["object_off"])
                    if obj is None:
                        continue
                    blob = data[obj["blob_off"] : obj["end"]]
                    candidates = _common_text_frame_candidates(blob, text_box["text"])
                    frame = _text_box_structural_frame(blob, text_box["text"], format_version)
                    text_rows.append({
                        "file": path.name,
                        "page": page_name,
                        "object_off": text_box["object_off"],
                        "text_len": len(text_box["text"]),
                        "candidate_count": len(candidates),
                        "candidates": candidates,
                        "structural_frame_off": frame["off"] if frame else None,
                        "structural_frame": {
                            "frame_size": frame["frame_size"],
                            "trailing_newlines": len(frame["text"]) - len(text_box["text"]),
                            "spans": len(frame["spans"]),
                            "paragraphs": len(frame["paragraphs"]),
                            "margins": frame["margins"],
                            "gravity": frame["gravity"],
                            "sections": frame["sections"],
                        } if frame else None,
                        "structural_spans_match_scan":
                            _text_box_span_agreement(frame, text_box) if frame else None,
                        "angle_deg": text_box.get("angle_deg"),
                    })
                for kind in ("images", "drawings"):
                    for item in page[kind]:
                        obj = _object_by_off(page, item["object_off"])
                        if obj is None:
                            continue
                        blob = data[obj["blob_off"] : obj["end"]]
                        known_rel = item["media_index_off"] - obj["blob_off"]
                        offsets = _u32_offsets(blob, item["media_index"])
                        media_record = _media_record_by_index(media_info).get(item["media_index"])
                        media_rows.append({
                            "file": path.name,
                            "page": page_name,
                            "kind": "painting" if kind == "drawings" else "image",
                            "object_off": item["object_off"],
                            "object_type": obj["raw_type"],
                            "media_index": item["media_index"],
                            "known_ref_rel": known_rel,
                            "u32_ref_offsets": offsets,
                            "known_ref_is_u32": known_rel in offsets,
                            "known_ref_rel_profile": f"{obj['raw_type']}:{len(blob)}:{known_rel}",
                            "raster_media_index": item["media_index"] in raster_indices,
                            "media_record_name": media_record.get("name") if media_record else None,
                            "media_record_ref_count": media_record.get("ref_count") if media_record else None,
                        })
        voice_rows.extend(_voice_rows(path, media_info, page_object_type_counts))
    end_tag_variant_gaps = {
        "nonzero_property_flags": sum(1 for row in end_tag_rows if row["property_flags"]),
        "landscape": sum(1 for row in end_tag_rows if row["is_landscape"]),
        "nonempty_sdk_strings": sum(
            1
            for row in end_tag_rows
            if any(row[key] for key in (
                "has_note_uuid",
                "has_cover_image",
                "has_app_name",
                "has_owner_id",
                "has_fixed_font",
                "has_app_custom_data",
            ))
        ),
        "skipped_blocks": sum(1 for row in end_tag_rows if row["skipped_size"]),
        "encryption_blocks": sum(1 for row in end_tag_rows if row["encryption_data_size"]),
    }
    return {
        "summary": {
            "end_tag_files": len(end_tag_rows),
            "end_tag_page_models": dict(Counter(row["page_model"] for row in end_tag_rows)),
            "end_tag_variant_gaps": end_tag_variant_gaps,
            "note_text_surfaces": len(note_text_rows),
            "note_text_common_frame_hits": sum(1 for row in note_text_rows if row["candidate_count"]),
            "text_boxes": len(text_rows),
            "text_common_frame_hits": sum(1 for row in text_rows if row["candidate_count"]),
            "text_structural_frames_found": sum(
                1 for row in text_rows if row["structural_frame_off"] is not None),
            "text_structural_spans_match": sum(
                1 for row in text_rows if row["structural_spans_match_scan"]),
            "text_structural_frame_offs": {
                f"rotated={rotated}:off={off}": count
                for (rotated, off), count in Counter(
                    (row["angle_deg"] not in (None, 0.0), row["structural_frame_off"])
                    for row in text_rows
                    if row["structural_frame_off"] is not None
                ).items()
            },
            "media_objects": len(media_rows),
            "media_known_ref_u32_hits": sum(1 for row in media_rows if row["known_ref_is_u32"]),
            "media_by_kind": dict(Counter(row["kind"] for row in media_rows)),
            "media_known_ref_profiles": dict(Counter(row["known_ref_rel_profile"] for row in media_rows)),
            "voice_clips": len(voice_rows),
            "voice_clips_linked_to_audio_media": sum(1 for row in voice_rows if row["media_record_is_audio"]),
            "page_audio_type10_objects": page_object_type_counts_total.get(10, 0),
        },
        "end_tag_rows": end_tag_rows,
        "note_text_rows": note_text_rows,
        "text_rows": text_rows,
        "media_rows": media_rows,
        "voice_rows": voice_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*", help="files or directories (default: samples/)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect(args.paths or [Path("samples")])
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    summary = report["summary"]
    print(
        f"end_tag variants: files={summary['end_tag_files']} "
        f"page_models={summary['end_tag_page_models']} gaps={summary['end_tag_variant_gaps']}"
    )
    print(
        f"note text_core candidates: surfaces={summary['note_text_surfaces']} "
        f"common_frame_hits={summary['note_text_common_frame_hits']}"
    )
    print(
        f"text_core candidates: text_boxes={summary['text_boxes']} "
        f"common_frame_hits={summary['text_common_frame_hits']} "
        f"structural_frames={summary['text_structural_frames_found']} "
        f"structural_spans_match={summary['text_structural_spans_match']} "
        f"frame_offs(rotated,off)={summary['text_structural_frame_offs']}"
    )
    print(
        f"media object refs: objects={summary['media_objects']} "
        f"known_ref_u32_hits={summary['media_known_ref_u32_hits']} "
        f"by_kind={summary['media_by_kind']}"
    )
    print(f"media ref profiles: {summary['media_known_ref_profiles']}")
    print(
        f"audio leads: voice_clips={summary['voice_clips']} "
        f"linked_to_audio_media={summary['voice_clips_linked_to_audio_media']} "
        f"page_type10_objects={summary['page_audio_type10_objects']}"
    )
    for row in report["note_text_rows"]:
        if row["candidate_count"]:
            print(
                f"  NOTE-TEXT {row['file']} {row['surface']} "
                f"candidates={row['candidates']}"
            )
    for row in report["text_rows"]:
        if row["candidate_count"]:
            print(
                f"  TEXT {row['file']} {row['page']} object=0x{row['object_off']:x} "
                f"candidates={row['candidates']}"
            )
    for row in report["voice_rows"]:
        print(
            f"  VOICE {row['file']} {row['label']} media={row['media_index_candidate']} "
            f"name={row['media_record_name']} display_ms={row['duration_ms_display']} "
            f"actual_ms={row['actual_duration_ms_candidate']} page_type10={row['page_audio_object_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
