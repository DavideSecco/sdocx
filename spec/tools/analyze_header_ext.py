"""Corpus diagnostics for the `.page` object-header HDR_EXT block.

This is an RE aid, not a validator. It exports every object whose common header
has the 0x40000 `HDR_EXT` block, plus summaries useful for deciding whether
`counter` or `seq` deserve a semantic name.

    .venv/bin/python spec/tools/analyze_header_ext.py samples
    .venv/bin/python spec/tools/analyze_header_ext.py samples --json
    .venv/bin/python spec/tools/analyze_header_ext.py samples --csv /tmp/hdr_ext.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_pages, load_page
from pysdocx.page import parse_page


def _iter_sdocx_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def _iter_objects_with_context(objects: list[dict], path: tuple[int, ...] = (), depth: int = 0):
    for obj in objects:
        obj_path = path + (obj["idx"],)
        yield obj, obj_path, depth
        yield from _iter_objects_with_context(obj["children"], obj_path, depth + 1)


def _bbox_width_height(bbox: tuple[float, float, float, float] | None) -> tuple[float | None, float | None]:
    if bbox is None:
        return None, None
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def collect_header_ext_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for file_path in _iter_sdocx_paths(paths):
        object_order = 0
        for page_index, page_name in enumerate(list_pages(file_path), 1):
            _, page_data = load_page(file_path, page_name)
            page = parse_page(page_data)
            for layer in page["layers"]:
                for obj, obj_path, depth in _iter_objects_with_context(layer["objects"]):
                    object_order += 1
                    header = obj.get("header") or {}
                    ext = header.get("ext_block")
                    if not ext:
                        continue
                    profile = obj.get("header_profile") or {}
                    bbox_w, bbox_h = _bbox_width_height(obj.get("bbox"))
                    rows.append({
                        "file": file_path.name,
                        "page_index": page_index,
                        "page_uuid": page["uuid"],
                        "page_width": page["width"],
                        "page_height": page["height"],
                        "layer_idx": layer["idx"],
                        "layer_uuid": layer["uuid"],
                        "layer_object_count": layer["object_count"],
                        "object_order": object_order,
                        "object_path": ".".join(str(part) for part in obj_path),
                        "depth": depth,
                        "raw_type": obj["raw_type"],
                        "object_type": obj["type"],
                        "object_off": obj["off"],
                        "blob_off": obj["blob_off"],
                        "blob_end": obj["end"],
                        "blob_size": obj["size"],
                        "child_count": obj["child_count"],
                        "header_uuid": header.get("uuid"),
                        "header_total_size": header.get("total_size"),
                        "header_flags": header.get("flags"),
                        "field_flags": header.get("field_flags"),
                        "format_version": header.get("format_version"),
                        "modified_time": header.get("modified_time"),
                        "timestamp": header.get("timestamp"),
                        "bbox_width": bbox_w,
                        "bbox_height": bbox_h,
                        "profile_family": profile.get("family"),
                        "profile_signature": profile.get("signature"),
                        "ext_off": ext["off"],
                        "counter": ext["counter"],
                        "seq": ext["seq"],
                        "ext_page_width": ext["page_width"],
                        "ext_page_height": ext["page_height"],
                        "ext_dims_match": (ext["page_width"], ext["page_height"]) == (page["width"], page["height"]),
                        "has_angle": bool(header.get("field_flags", 0) & 0x1),
                        "has_extra_key": bool(header.get("field_flags", 0) & 0x20),
                    })
    return rows


def summarize_header_ext(rows: list[dict]) -> dict:
    by_file: list[dict] = []
    for file_name in sorted({row["file"] for row in rows}):
        file_rows = [row for row in rows if row["file"] == file_name]
        seqs = [row["seq"] for row in file_rows]
        counters = Counter(row["counter"] for row in file_rows)
        by_file.append({
            "file": file_name,
            "count": len(file_rows),
            "object_types": dict(sorted(Counter(row["object_type"] for row in file_rows).items())),
            "seq_min": min(seqs),
            "seq_max": max(seqs),
            "seq_unique": len(set(seqs)),
            "seq_values": sorted(set(seqs)),
            "seq_inversions_in_object_order": sum(
                1 for prev, cur in zip(file_rows, file_rows[1:]) if cur["seq"] < prev["seq"]
            ),
            "counter_unique": len(counters),
            "counter_repeated_groups": sum(1 for count in counters.values() if count > 1),
            "counter_repeated_size_counts": dict(sorted(Counter(c for c in counters.values() if c > 1).items())),
            "ext_offsets": sorted({row["ext_off"] for row in file_rows}),
        })

    repeated_counter_examples = []
    for (file_name, counter), group in sorted(_groups(rows, "file", "counter").items()):
        if len(group) <= 1:
            continue
        repeated_counter_examples.append({
            "file": file_name,
            "counter": counter,
            "count": len(group),
            "object_types": dict(sorted(Counter(row["object_type"] for row in group).items())),
            "seq_values": sorted({row["seq"] for row in group}),
            "pages": sorted({row["page_uuid"][:8] for row in group}),
            "object_paths": [
                f"p{row['page_index']}/l{row['layer_idx']}/{row['object_path']}"
                for row in group[:8]
            ],
        })

    return {
        "count": len(rows),
        "dimension_mismatches": [
            {
                "file": row["file"],
                "page_uuid": row["page_uuid"],
                "object_off": row["object_off"],
                "decoded": [row["ext_page_width"], row["ext_page_height"]],
                "page": [row["page_width"], row["page_height"]],
            }
            for row in rows
            if not row["ext_dims_match"]
        ],
        "by_object_type": dict(sorted(Counter(row["object_type"] for row in rows).items())),
        "by_profile_signature": dict(sorted(Counter(row["profile_signature"] for row in rows).items())),
        "by_ext_offset": dict(sorted(Counter(row["ext_off"] for row in rows).items())),
        "by_file": by_file,
        "repeated_counter_examples": repeated_counter_examples[:20],
    }


def _groups(rows: list[dict], *keys: str) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return grouped


def print_summary(summary: dict) -> None:
    print(
        f"hdr_ext rows={summary['count']} "
        f"dimension_mismatches={len(summary['dimension_mismatches'])}"
    )
    print(f"by object type: {summary['by_object_type']}")
    print(f"by profile signature: {summary['by_profile_signature']}")
    print(f"by ext offset: {summary['by_ext_offset']}")
    print("per file:")
    for row in summary["by_file"]:
        print(
            f"  {row['file']:<58} n={row['count']:<4} "
            f"types={row['object_types']} seq={row['seq_min']}..{row['seq_max']} "
            f"uniq={row['seq_unique']} inv={row['seq_inversions_in_object_order']} "
            f"counters={row['counter_unique']} repeated={row['counter_repeated_groups']} "
            f"repeat_sizes={row['counter_repeated_size_counts']} offsets={row['ext_offsets']}"
        )
    if summary["repeated_counter_examples"]:
        print("repeated counter examples:")
        for row in summary["repeated_counter_examples"][:12]:
            print(
                f"  {row['file']:<58} counter={row['counter']:<8} count={row['count']:<3} "
                f"types={row['object_types']} seq={row['seq_values']} pages={row['pages']} "
                f"objects={row['object_paths']}"
            )


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*", help="files or directories to scan (default: samples/)")
    parser.add_argument("--json", action="store_true", help="emit rows + summary as JSON")
    parser.add_argument("--csv", type=Path, help="write per-object rows as CSV")
    args = parser.parse_args()

    rows = collect_header_ext_rows(args.paths or [Path("samples")])
    summary = summarize_header_ext(rows)
    if args.csv:
        write_csv(args.csv, rows)
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
    else:
        print_summary(summary)
        if args.csv:
            print(f"wrote CSV rows to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
