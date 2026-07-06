"""Cross-check the Kaitai .page layer/object tree against pysdocx on the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_page_tree.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_page import SdocxPage  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.page import _iter_objects, parse_page, parse_page_tree  # noqa: E402


def _flatten_kaitai_objects(objects, pos: int):
    out = []
    for obj in objects:
        blob_off = pos + 7
        end = blob_off + obj.blob_size
        out.append({
            "off": pos,
            "blob_off": blob_off,
            "end": end,
            "raw_type": obj.raw_type,
            "child_count": obj.child_count,
            "size": obj.blob_size,
        })
        child_rows, pos = _flatten_kaitai_objects(obj.children, end)
        out.extend(child_rows)
    return out, pos


def _layer_static_and_optional_len(layer) -> int:
    n = 16
    if layer.content_flags & 0x01:
        n += 1
    if layer.content_flags & 0x02:
        n += 4
    if layer.content_flags & 0x04:
        n += 2 + layer.content_04_text.char_len * 2
    if layer.content_flags & 0x08:
        n += 2 + layer.layer_uuid.char_len * 2
    if layer.content_flags & 0x10:
        n += 8
    if layer.content_flags & 0x20:
        n += 4
    return n


def _tree_diffs(data: bytes) -> list[str]:
    ref_page = parse_page(data)
    ref = parse_page_tree(data, ref_page["width"], ref_page["height"], ref_page["base"])
    k = SdocxPage.from_bytes(data)
    kt = k.tree
    diffs = []
    if kt.layer_count != len(ref["layers"]):
        diffs.append(f"layer_count {kt.layer_count}!={len(ref['layers'])}")
    if kt.current_layer_index != ref["current_layer_index"]:
        diffs.append("current_layer_index")

    pos = k.base + 4
    for i, (kl, rl) in enumerate(zip(kt.layers, ref["layers"])):
        prefix_off = pos
        layer_off = prefix_off + 4
        if layer_off != rl["off"]:
            diffs.append(f"layer[{i}].off")
        if kl.layer_prefix != rl["prefix"]:
            diffs.append(f"layer[{i}].prefix")
        if kl.next_offset != rl["next_offset"]:
            diffs.append(f"layer[{i}].next_offset")
        if (kl.flag1, kl.flag2, kl.flag3) != rl["flags"]:
            diffs.append(f"layer[{i}].flags")
        if kl.content_flags != rl["content_flags"]:
            diffs.append(f"layer[{i}].content_flags")
        if kl.layer_flags != rl["layer_flags"]:
            diffs.append(f"layer[{i}].layer_flags")
        got_uuid = kl.layer_uuid.value if kl.content_flags & 0x08 else ""
        if got_uuid != rl["uuid"]:
            diffs.append(f"layer[{i}].uuid")
        got_modified = kl.modified_time if kl.content_flags & 0x10 else None
        if got_modified != rl["modified_time"]:
            diffs.append(f"layer[{i}].modified_time")
        if kl.object_count != rl["object_count"]:
            diffs.append(f"layer[{i}].object_count")

        objects_pos = prefix_off + _layer_static_and_optional_len(kl) + 4
        k_objects, end_pos = _flatten_kaitai_objects(kl.objects, objects_pos)
        r_objects = list(_iter_objects(rl["objects"]))
        if len(k_objects) != len(r_objects):
            diffs.append(f"layer[{i}].recursive_object_count {len(k_objects)}!={len(r_objects)}")
        for j, (ko, ro) in enumerate(zip(k_objects, r_objects)):
            for field in ("off", "blob_off", "end", "raw_type", "child_count", "size"):
                if ko[field] != ro[field]:
                    diffs.append(f"layer[{i}].object[{j}].{field}")
        if kl.layer_hash.hex() != rl["hash"]:
            diffs.append(f"layer[{i}].hash")
        pos = end_pos + 32
    return diffs


def main() -> int:
    ok = failures = pages = objects = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".page")):
                data = z.read(name)
                pages += 1
                try:
                    ref_page = parse_page(data)
                    tree = parse_page_tree(data, ref_page["width"], ref_page["height"], ref_page["base"])
                    diffs = _tree_diffs(data)
                except ValueError as exc:
                    print(f"SKIP  {sample.name}/{name}: {exc}")
                    continue
                if diffs:
                    failures += 1
                    print(f"FAIL  {sample.name}/{name[:12]}: {diffs[:8]}")
                else:
                    ok += 1
                    objects += tree["object_count"]
    print(f"\n{ok} page trees matched, {failures} mismatched, {objects} objects, out of {pages} pages")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
