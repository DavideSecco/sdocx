"""Corpus diagnostics for common object-header fields that remain semantic Unknowns."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_pages, load_page  # noqa: E402
from pysdocx.page import _iter_objects, parse_page  # noqa: E402


def _paths(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")) + sorted(path.glob("*/note.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def collect_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in _paths(paths):
        object_order = 0
        for page_index, page_name in enumerate(list_pages(path), 1):
            page = parse_page(load_page(path, page_name)[1])
            for layer in page["layers"]:
                for obj in _iter_objects(layer["objects"]):
                    object_order += 1
                    header = obj.get("header")
                    if not header:
                        continue
                    ext = header.get("ext_block") or {}
                    extra = header.get("extra_key_block") or {}
                    rows.append({
                        "file": path.name,
                        "page_index": page_index,
                        "page_uuid": page["uuid"],
                        "layer_idx": layer["idx"],
                        "object_order": object_order,
                        "object_idx": obj["idx"],
                        "object_type": obj["type"],
                        "raw_type": obj["raw_type"],
                        "header_flags": header["flags"],
                        "field_flags": header["field_flags"],
                        "total_size": header["total_size"],
                        "profile_signature": (obj.get("header_profile") or {}).get("signature"),
                        "has_hdr_ext": bool(ext),
                        "hdr_counter": ext.get("counter"),
                        "hdr_seq": ext.get("seq"),
                        "has_extra_key": bool(extra),
                        "extra_key": extra.get("key"),
                        "extra_key_trailing": extra.get("trailing"),
                    })
    return rows


def summarize(rows: list[dict]) -> dict:
    flag_matrix: dict[str, Counter] = defaultdict(Counter)
    signature_flags: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        flag_matrix[row["object_type"]][f"0x{row['header_flags']:x}"] += 1
        signature_flags[row["profile_signature"]][f"0x{row['header_flags']:x}"] += 1

    ext_rows = [row for row in rows if row["has_hdr_ext"]]
    extra_rows = [row for row in rows if row["has_extra_key"]]
    repeated_counters = []
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in ext_rows:
        groups[(row["file"], row["hdr_counter"])].append(row)
    for (file_name, counter), group in sorted(groups.items()):
        if len(group) <= 1:
            continue
        repeated_counters.append({
            "file": file_name,
            "counter": counter,
            "count": len(group),
            "object_types": dict(sorted(Counter(row["object_type"] for row in group).items())),
            "seq_values": sorted({row["hdr_seq"] for row in group}),
        })

    return {
        "count": len(rows),
        "header_flags": {f"0x{k:x}": v for k, v in sorted(Counter(row["header_flags"] for row in rows).items())},
        "header_flags_by_object_type": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(flag_matrix.items())
        },
        "header_flags_by_signature": {
            str(key): dict(sorted(counter.items()))
            for key, counter in sorted(signature_flags.items())
        },
        "extra_key_count": len(extra_rows),
        "extra_key_trailing": dict(sorted(Counter(row["extra_key_trailing"] for row in extra_rows).items())),
        "extra_key_by_object_type": dict(sorted(Counter(row["object_type"] for row in extra_rows).items())),
        "hdr_ext_count": len(ext_rows),
        "hdr_seq_values": sorted({row["hdr_seq"] for row in ext_rows}),
        "hdr_repeated_counter_groups": len(repeated_counters),
        "hdr_repeated_counter_examples": repeated_counters[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*", help="files or directories (default: samples/)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = collect_rows(args.paths or [Path("samples")])
    summary = summarize(rows)
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
        return 0
    print(f"object headers={summary['count']}")
    print(f"header_flags={summary['header_flags']}")
    print("header_flags_by_object_type:")
    for key, value in summary["header_flags_by_object_type"].items():
        print(f"  {key:<14} {value}")
    print("header_flags_by_signature:")
    for key, value in summary["header_flags_by_signature"].items():
        print(f"  {key:<12} {value}")
    print(
        f"extra_key_count={summary['extra_key_count']} "
        f"trailing={summary['extra_key_trailing']} by_type={summary['extra_key_by_object_type']}"
    )
    print(
        f"hdr_ext_count={summary['hdr_ext_count']} seq_values={summary['hdr_seq_values']} "
        f"repeated_counter_groups={summary['hdr_repeated_counter_groups']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
