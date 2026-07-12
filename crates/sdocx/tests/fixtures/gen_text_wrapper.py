#!/usr/bin/env python
"""Regenerate `text_wrapper_pysdocx.json` — the Text/Shape wrapper parity fixture.

Enumerates every `ObjectBase -> ShapeBase -> Shape -> Text` wrapper in the
corpus — note.note title/body Text blobs plus raw type-2 page text boxes — and
dumps, per wrapper, its `(src member, off, size)` window plus the structural
fields pysdocx `parse_text_wrapper` decodes. `crates/sdocx/src/note_doc.rs`'s
wrapper unit test slices the same window out of the same member and asserts the
Rust `parse_text_wrapper` agrees field-for-field.

The fixture stores NO note text (only char/span counts and geometry), so it is
safe to commit; the user's personal `Appunti vari` samples are skipped anyway,
matching the other fixtures.

Run from the repo root with the uv venv:
    .venv/bin/python crates/sdocx/tests/fixtures/gen_text_wrapper.py
"""
from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

from pysdocx.note_doc import parse_note_doc, parse_text_wrapper

REPO = Path(__file__).resolve().parents[4]
SAMPLES = REPO / "samples"
OUT = Path(__file__).resolve().parent / "text_wrapper_pysdocx.json"


def fields(raw: bytes) -> dict:
    """The structural fields the Rust parity gate compares (no note text)."""
    ref = parse_text_wrapper(raw)
    common = ref["common"]
    trailing = ref["trailing_hash_like"]
    return {
        "object_base_size": ref["object_base"]["size"],
        "shape_base_size": ref["shape_base"]["size"],
        "shape_size": ref["shape"]["size"],
        "text_size": ref["text"]["size"],
        "shape_type": ref["shape_type"],
        "original_rect": list(ref["original_rect"]),
        "original_angle": ref["original_angle"],
        "base_angle": ref["base_angle"],
        "base_pivot": list(ref["base_pivot"]) if ref["base_pivot"] is not None else None,
        "path_hex": ref["path_raw"],
        "control_points": [list(p) for p in ref["control_points"]],
        "ellipsis_type": ref["ellipsis_type"],
        "text_auto_fit_type": ref["text_auto_fit_type"],
        "border_colour": ref["border_colour"],
        "border_width": ref["border_width"],
        "border_type": ref["border_type"],
        "trailing_len": len(trailing) // 2 if trailing else 0,
        "has_common": common is not None,
        "common_char_count": len(common["text"]) if common else 0,
        "common_span_count": len(common["spans"]) if common else 0,
    }


def wrappers_for(z: zipfile.ZipFile) -> list[dict]:
    out: list[dict] = []
    note = z.read("note.note")
    doc = parse_note_doc(note)
    for kind in ("title", "body"):
        off, size = doc[f"{kind}_off"], doc[f"{kind}_size"]
        entry = {"src": "note.note", "off": off, "size": size}
        entry.update(fields(note[off:off + size]))
        out.append(entry)

    for member in z.namelist():
        if not member.endswith(".page"):
            continue
        data = z.read(member)
        # Locate locally framed raw-type-2 object entries the same way the
        # pysdocx validator does: a candidate has the exact
        # [type, child_count, blob_size, blob] envelope and passes the full
        # four-frame parser. Mirrors spec/tools/validate_text_wrapper.py.
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
                fs = fields(raw)
            except Exception:
                continue
            out.append({"src": member, "off": blob_off, "size": size, **fs})
    return out


def main() -> None:
    result: dict = {}
    for sample in sorted(SAMPLES.glob("*.sdocx")):
        if sample.name.startswith("Appunti vari"):
            continue  # personal — keep out of the committed fixture
        with zipfile.ZipFile(sample) as z:
            result[sample.name] = wrappers_for(z)

    OUT.write_text(json.dumps(result, indent=1) + "\n")
    n = sum(len(v) for v in result.values())
    print(f"wrote {OUT} ({n} wrappers across {len(result)} samples)")


if __name__ == "__main__":
    main()
