#!/usr/bin/env python3
"""Cross-check the Text/Shape Kaitai wrapper against pysdocx on the corpus."""
from __future__ import annotations

import sys
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spec" / "generated"))

from sdocx_text_wrapper import SdocxTextWrapper  # noqa: E402
from pysdocx.note_doc import parse_note_doc, parse_text_wrapper  # noqa: E402


def iter_wrappers():
    for sample in sorted(list((ROOT / "samples").glob("*.sdocx")) + list((ROOT / "samples").glob("*/note.sdocx"))):
        with zipfile.ZipFile(sample) as z:
            note = z.read("note.note")
            doc = parse_note_doc(note)
            for kind in ("title", "body"):
                off, size = doc[f"{kind}_off"], doc[f"{kind}_size"]
                yield f"{sample.name}:note.{kind}", note[off:off + size]
            for member in z.namelist():
                if not member.endswith(".page"):
                    continue
                data = z.read(member)
                # Locate locally framed raw-type-2 object entries without
                # materialising huge handwriting-only trees. A candidate must
                # have the exact [type, child_count, blob_size, blob] envelope
                # and then pass the complete four-frame Text parser.
                entry_off = data.find(b"\x02")
                while 0 <= entry_off < len(data) - 22:
                    blob_off = entry_off + 7
                    entry_off = data.find(b"\x02", entry_off + 1)
                    if data[blob_off + 4:blob_off + 6] != b"\0\0":
                        continue
                    size = struct.unpack_from("<I", data, blob_off - 4)[0]
                    end = blob_off + size
                    if size < 200 or end > len(data):
                        continue
                    raw = data[blob_off:end]
                    try:
                        parse_text_wrapper(raw)
                    except Exception:
                        continue
                    yield f"{sample.name}:{member}:blob@{blob_off}", raw


def diffs_for(raw: bytes) -> list[str]:
    ref = parse_text_wrapper(raw)
    k = SdocxTextWrapper.from_bytes(raw)
    diffs: list[str] = []

    def eq(name, got, expected):
        if got != expected:
            diffs.append(name)

    eq("object_base.size", k.object_base.size, ref["object_base"]["size"])
    eq("object_base.type", k.object_base.body.header.data_type, 0)
    eq("object_base.format_version", k.object_base.body.format_version,
       int.from_bytes(raw[ref["object_base"]["header_end"]:
                          ref["object_base"]["header_end"] + 4], "little"))
    eq("shape_base.size", k.shape_base.size, ref["shape_base"]["size"])
    eq("shape_base.type", k.shape_base.body.header.data_type, 6)
    eq("shape.size", k.shape.size, ref["shape"]["size"])
    eq("shape.type", k.shape.body.header.data_type, 7)
    eq("shape.shape_type", k.shape.body.shape_type, ref["shape_type"])
    eq("shape.original_rect", tuple(k.shape.body.original_rect), ref["original_rect"])
    eq("shape.original_angle", k.shape.body.original_angle, ref["original_angle"])
    eq("shape.path", k.shape.body.path.hex(), ref["path_raw"])
    eq("shape.control_points",
       [(p.x, p.y) for p in k.shape.body.control_points], ref["control_points"])
    eq("shape.shape_field_11_f32", getattr(k.shape.body, "shape_field_11_f32", None),
       ref["shape_field_11_f32"])
    eq("shape.ellipsis_type", getattr(k.shape.body, "ellipsis_type", None), ref["ellipsis_type"])
    eq("shape.text_auto_fit_type", getattr(k.shape.body, "text_auto_fit_type", None),
       ref["text_auto_fit_type"])
    common = ref["common"]
    eq("common.text", k.shape.body.common.text_utf16, common["text"])
    eq("common.spans", len(k.shape.body.common.spans), len(common["spans"]))
    eq("common.strikethrough_enabled",
       [s.strikethrough_enabled for s in k.shape.body.common.spans
        if s.span_type == 20],
       [bytes.fromhex(s["extra"])[0] for s in common["spans"]
        if s["span_type"] == 20])
    eq("common.paragraphs", len(k.shape.body.common.paragraphs), len(common["paragraphs"]))
    eq("common.margins", list(k.shape.body.common.margins), common["margins"])
    eq("common.gravity", k.shape.body.common.gravity, common["gravity"])
    eq("common.sections",
       [(s.text_start, s.text_length) for s in k.shape.body.common.sections],
       common["sections"])
    eq("text.size", k.text.size, ref["text"]["size"])
    eq("text.type", k.text.body.header.data_type, 2)
    eq("text.border_colour",
       getattr(k.text.body, "border_colour", None).hex()
       if getattr(k.text.body, "border_colour", None) is not None else None,
       ref["border_colour"])
    eq("text.border_width", getattr(k.text.body, "border_width", None), ref["border_width"])
    eq("text.border_type", getattr(k.text.body, "border_type", None), ref["border_type"])
    eq("trailing_hash_like", k.trailing_hash_like.hex(), ref["trailing_hash_like"] or "")
    return diffs


if __name__ == "__main__":
    bad = 0
    count = 0
    for where, raw in iter_wrappers():
        diffs = diffs_for(raw)
        count += 1
        if diffs:
            bad += 1
            print(where, ", ".join(diffs))
    print(f"{count - bad} matched, {bad} mismatched, out of {count} wrappers")
    raise SystemExit(bool(bad))
