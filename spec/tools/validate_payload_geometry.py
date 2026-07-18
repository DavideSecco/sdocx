"""Cross-check the Kaitai payload-geometry spec against pysdocx across the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_payload_geometry.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_payload_geometry import SdocxPayloadGeometry  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.page import (  # noqa: E402
    _decode_payload_geometry,
    _iter_objects,
    _parse_object_header,
    parse_page,
    parse_page_tree,
)


def _diffs(blob: bytes) -> list[str] | None:
    header = _parse_object_header(blob)
    ref = _decode_payload_geometry(blob, header)
    if ref is None:
        return None  # no wrapper on this object
    k = SdocxPayloadGeometry.from_bytes(blob[header["total_size"]:])
    out = []
    if k.l0 != ref["l0"] or k.l1 != ref["l1"] or k.tag != ref["tag"]:
        out.append("lengths")
    if k.point_count != ref["point_count"]:
        out.append("point_count")
    if [(p.x, p.y) for p in k.points] != ref["points"]:
        out.append("points")
    return out


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx") + ((ROOT / "samples").glob("*/note.sdocx")):
        with zipfile.ZipFile(sample) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".page")):
                data = z.read(name)
                try:
                    base = parse_page(data)["base"]
                except ValueError:
                    continue
                tree = parse_page_tree(data, 0, 0, base)
                for layer in tree["layers"]:
                    for obj in _iter_objects(layer["objects"]):
                        d = _diffs(data[obj["blob_off"]:obj["end"]])
                        if d is None:
                            continue
                        if d:
                            failures += 1
                            print(f"FAIL  {sample.name}/{name[:12]} obj@{obj['blob_off']}: {d}")
                        else:
                            ok += 1
    print(f"\n{ok} wrappers matched, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
