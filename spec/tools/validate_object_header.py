"""Cross-check the Kaitai object-header spec against pysdocx for every object in the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_object_header.py
"""
import os
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_object_header import SdocxObjectHeader  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.page import _iter_objects, _parse_object_header, parse_page, parse_page_tree  # noqa: E402

BASE_FIELDS = [
    "total_size", "data_type", "var_data_offset", "flags", "field_flags",
    "format_version", "uuid", "modified_time", "timestamp", "resizable",
]


def _objects(data: bytes):
    base = parse_page(data)["base"]
    tree = parse_page_tree(data, 0, 0, base)
    for layer in tree["layers"]:
        for obj in _iter_objects(layer["objects"]):
            yield data[obj["blob_off"]:obj["end"]]


def _diffs(blob: bytes) -> list[str]:
    ref = _parse_object_header(blob)
    if ref is None:
        return ["pysdocx_rejected"]
    k = SdocxObjectHeader.from_bytes(blob)
    out = [f for f in BASE_FIELDS if ref[f] != getattr(k, f)]
    if struct.pack("<4d", *k.bbox) != struct.pack("<4d", *ref["bbox"]):
        out.append("bbox")
    if ref["field_flags"] & 0x20:
        ek = ref["extra_key_block"]
        if k.extra_key is None or k.extra_key.key.rstrip("\x00") != ek["key"] \
                or k.extra_key.trailing != ek["trailing"]:
            out.append("extra_key")
    if ref["field_flags"] & 0x40000:
        ex = ref["ext_block"]
        if k.hdr_ext is None or (k.hdr_ext.counter, k.hdr_ext.seq,
                                 k.hdr_ext.page_width, k.hdr_ext.page_height) != \
                (ex["counter"], ex["seq"], ex["page_width"], ex["page_height"]):
            out.append("hdr_ext")
    return out


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
            page_names = [n for n in z.namelist() if n.endswith(".page")]
        n_ok = n_bad = 0
        with zipfile.ZipFile(sample) as z:
            for name in sorted(page_names):
                data = z.read(name)
                try:
                    objects = list(_objects(data))
                except ValueError:
                    continue
                for blob in objects:
                    d = _diffs(blob)
                    if d:
                        n_bad += 1
                        if n_bad <= 3:
                            print(f"FAIL  {sample.name}/{name[:12]}: {d}")
                    else:
                        n_ok += 1
        ok += n_ok
        failures += n_bad
        print(f"{'OK  ' if not n_bad else 'FAIL'}  {sample.name}: {n_ok} objects")
    print(f"\n{ok} objects matched, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
