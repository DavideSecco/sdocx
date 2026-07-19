"""Cross-check type-13 Web inline objects against pysdocx."""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_web_object import SdocxWebObject  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.note_doc import (  # noqa: E402
    note_doc_common_frames, parse_note_doc, parse_web_inline_object,
)


def diffs_for(raw: bytes) -> list[str]:
    ref = parse_web_inline_object(raw, 0, len(raw))
    k = SdocxWebObject.from_bytes(raw)
    f = k.frame
    diffs = []
    pairs = {
        "object_base_size": k.object_base_size,
        "frame_size": k.frame_size,
        "object_type": f.object_type,
        "flex_offset": f.flex_offset,
        "property_flags": f.property_flags.value,
        "field_flags": f.field_flags.value,
        "thumbnail_file_id": getattr(f, "thumbnail_file_id", None),
        "image_type_id": f.image_type_id,
        "version": getattr(f, "version", None),
        "view_type": getattr(f, "view_type", None),
    }
    for name, value in pairs.items():
        if ref.get(name) != value:
            diffs.append(name)
    for name in ("body", "title", "uri"):
        if ref.get(name) != getattr(f, name).value:
            diffs.append(name)
    if ref.get("field_7_opaque") != f.field_7_opaque.raw.hex():
        diffs.append("field_7_opaque")
    if not k.consumes_eof or not f.flex_offset_matches or f.has_unhandled_field_flags:
        diffs.append("structural_gate")
    return diffs


def iter_web_objects():
    for sample in sorted(list((ROOT / "samples").glob("*.sdocx")) + list((ROOT / "samples").glob("*/note.sdocx"))):
        with zipfile.ZipFile(sample) as z:
            if "note.note" not in z.namelist():
                continue
            note = z.read("note.note")
        doc = parse_note_doc(note)
        body_blob = note[doc["body_off"]:doc["body_off"] + doc["body_size"]]
        body = note_doc_common_frames(note, doc)["body"]
        if body and body.get("inline"):
            for obj in body["inline"]["objects"]:
                if obj["object_type"] == 13:
                    yield sample, body_blob[obj["body_off"]:obj["body_off"] + obj["obj_size"]]


def main() -> int:
    count = failures = 0
    for sample, raw in iter_web_objects():
        count += 1
        diffs = diffs_for(raw)
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: {diffs}")
        else:
            print(f"OK    {sample.name}: {len(raw)} bytes")
    print(f"\n{count - failures} matched, {failures} mismatched, {count} Web objects")
    return 1 if failures or count == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
