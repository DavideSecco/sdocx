"""Cross-check the Kaitai note.note spec against pysdocx on the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_note.py

The Kaitai spec models the whole `note.note` member sequentially; this
validator compares it field-by-field against the structural reference parser
`pysdocx.note_doc.parse_note_doc` (which itself is gated on landing exactly on
the trailing hash) and against the legacy header parse in
`pysdocx.note.parse_note_metadata`.
"""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_note import SdocxNote  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.note import parse_note_metadata  # noqa: E402
from pysdocx.note_doc import parse_note_doc  # noqa: E402

# doc-field name -> kaitai attribute (both on the top-level object).
SCALAR_FIELDS = {
    "flex_offset": "flex_offset",
    "format_version": "format_version",
    "file_revision": "file_revision",
    "created_time_us": "created_time_us",
    "modified_time_us": "modified_time_us",
    "width": "width",
    "height": "height",
    "page_h_padding": "page_h_padding",
    "page_v_padding": "page_v_padding",
    "min_format_version": "min_format_version",
    "title_size": "title_size",
    "body_size": "body_size",
}

# flex field name in doc["fields"] -> plain-scalar kaitai attribute.
SCALAR_FLEX_FIELDS = {
    "last_edited_page_index": "last_edited_page_index",
    "last_edited_page_image_id": "last_edited_page_image_id",
    "last_edited_page_time_us": "last_edited_page_time_us",
    "body_text_font_size_delta": "body_text_font_size_delta",
    "server_check_point": "server_check_point",
    "fixed_text_direction": "fixed_text_direction",
    "fixed_background_theme": "fixed_background_theme",
    "stroke_group_size": "stroke_group_size",
}

PEN_FIELDS = (
    "name", "color", "is_curvable", "advanced_settings",
    "is_eraser_enabled", "size_level", "particle_density", "ui_color_info",
)
PEN_FULL_EXTRA = ("particle_size", "is_fixed_width", "is_fixed_opacity",
                  "is_auto_size_enabled", "fit_ratio")


def _check_pen(diffs: list, label: str, ref: dict, k_pen, full: bool) -> None:
    body = k_pen.body if full else k_pen
    for field in PEN_FIELDS + (PEN_FULL_EXTRA if full else ()):
        # Kaitai leaves `if:`-gated trailing attributes unset when absent.
        k_value = getattr(body, field, None)
        if field == "color":
            k_value = k_value.hex()
        elif field == "name" or field == "advanced_settings":
            k_value = k_value.value
        if ref[field] != k_value:
            diffs.append(f"{label}.{field}")
    if abs(ref["size"] - body.pen_size) > 1e-6:
        diffs.append(f"{label}.size")
    if any(abs(a - b) > 1e-6 for a, b in zip(ref["ui_color_hsv"], body.ui_color_hsv)):
        diffs.append(f"{label}.ui_color_hsv")


def diffs_for(data: bytes) -> list[str]:
    """All Kaitai-vs-pysdocx disagreements for one note.note; [] when clean."""
    doc = parse_note_doc(data)
    meta = parse_note_metadata(data)
    k = SdocxNote.from_bytes(data)
    diffs = []

    for doc_field, k_field in SCALAR_FIELDS.items():
        if doc[doc_field] != getattr(k, k_field):
            diffs.append(doc_field)
    if doc["property_flags"] != k.property_flags.value:
        diffs.append("property_flags")
    if doc["field_flags"] != k.field_flags.value:
        diffs.append("field_flags")
    if doc["id"] != k.note_id.value:
        diffs.append("note_id")
    if meta["meta_flags"] != k.field_flags.value:
        diffs.append("meta_flags_alias")
    if k.has_unhandled_field_bits:
        diffs.append("unhandled_field_bits")

    # Blob boundaries and the gap.
    if data[doc["title_off"] : doc["title_off"] + doc["title_size"]] != k._raw_title_blob:
        diffs.append("title_blob")
    if data[doc["body_off"] : doc["body_off"] + doc["body_size"]] != k._raw_body_blob:
        diffs.append("body_blob")
    gap_pair = (
        list(k.pre_flex_gap.maybe_default_page_size)
        if doc["gap_size"] == 8 else None
    )
    if doc["gap_u32_pair"] != gap_pair:
        diffs.append("pre_flex_gap_pair")

    fields = doc["fields"]
    for doc_field, k_field in SCALAR_FLEX_FIELDS.items():
        # Kaitai leaves `if:`-gated attributes unset when absent.
        k_value = getattr(k, k_field, None)
        if fields.get(doc_field) != k_value:
            diffs.append(doc_field)

    if ("string_registry" in fields) != bool(k.has_string_registry):
        diffs.append("string_registry_presence")
    if "string_registry" in fields:
        ref_strings = fields["string_registry"]["strings"]
        k_strings = {
            e.string_id: e.value.value
            for e in (k.string_registry.body.entries if k.string_registry.body else ())
        }
        if ref_strings != k_strings:
            diffs.append("string_registry")

    if ("voice_data" in fields) != bool(k.has_voice_data):
        diffs.append("voice_data_presence")
    if "voice_data" in fields:
        for i, ref_rec in enumerate(fields["voice_data"]):
            k_rec = k.voice_data.recordings[i].body
            if (ref_rec["file_id"] != k_rec.file_id
                    or ref_rec["name"] != k_rec.name.value
                    or ref_rec["duration_str"] != k_rec.duration_str.value
                    or ref_rec["created_time_us"] != k_rec.created_time_us
                    or ref_rec["precise_duration_ms"] != k_rec.precise_duration_ms
                    or [(e["action"], e["time_us"]) for e in ref_rec["events"]]
                    != [(e.action, e.time_us) for e in k_rec.events]):
                diffs.append(f"voice_data[{i}]")

    if ("last_pen_info" in fields) != bool(k.has_last_pen_info):
        diffs.append("last_pen_info_presence")
    if "last_pen_info" in fields:
        _check_pen(diffs, "last_pen_info", fields["last_pen_info"],
                   k.last_pen_info, full=True)
    if ("compatible_last_pen_info" in fields) != bool(k.has_compatible_last_pen_info):
        diffs.append("compatible_last_pen_info_presence")
    if "compatible_last_pen_info" in fields:
        _check_pen(diffs, "compatible_last_pen_info",
                   fields["compatible_last_pen_info"],
                   k.compatible_last_pen_info, full=False)

    if ("attached_files" in fields) != bool(k.has_attached_files):
        diffs.append("attached_files_presence")
    if "attached_files" in fields:
        ref_files = [(f["name"], f["file_id"]) for f in fields["attached_files"]]
        k_files = [(e.name.value, e.file_id) for e in k.attached_files.entries]
        if ref_files != k_files:
            diffs.append("attached_files")

    # The structural gate: the sequence must land exactly on the hash.
    if not doc["landed_on_hash"]:
        diffs.append("pysdocx_landed_on_hash")
    if k.trailing_hash != data[-32:]:
        diffs.append("trailing_hash")
    if hashlib.sha256(data[:-32]).digest() != k.trailing_hash:
        diffs.append("trailing_hash_sha256_prefix")

    return diffs


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx") + ((ROOT / "samples").glob("*/note.sdocx")):
        with zipfile.ZipFile(sample) as z:
            if "note.note" not in z.namelist():
                print(f"SKIP  {sample.name}: no note.note")
                continue
            data = z.read("note.note")
        doc = parse_note_doc(data)
        diffs = diffs_for(data)
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: {diffs}")
        else:
            ok += 1
            print(
                f"OK    {sample.name} (fmt={doc['format_version']} "
                f"field_flags=0x{doc['field_flags']:x} gap={doc['gap_size']})"
            )
    print(f"\n{ok} matched, {failures} mismatched, out of {ok + failures} parsed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
