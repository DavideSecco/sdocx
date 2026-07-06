"""Diagnostics for timestamp-like fields across end_tag.bin, note.note, and tails."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_end_tag, list_media_info, load_note  # noqa: E402
from pysdocx.note import parse_note_metadata  # noqa: E402


def _paths(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def collect_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in _paths(paths):
        note_bytes = load_note(path)
        note = parse_note_metadata(note_bytes) if note_bytes else None
        end_tag = list_end_tag(path)
        media = list_media_info(path) or {"records": []}
        if note is None:
            continue
        row = {
            "file": path.name,
            "note_created": note["created_time"],
            "note_modified": note["modified_time"],
            "note_file_revision": note["file_revision"],
            "end_created_header_delta": None,
            "end_created_a_delta": None,
            "end_created_b_delta": None,
            "end_extra_delta_to_note_modified": None,
            "end_extra_nonzero": False,
            "tail_post_hash_matches_note_last_u32": [],
            "media_time_min_delta_to_note_modified": None,
            "media_time_max_delta_to_note_modified": None,
        }
        if end_tag is not None:
            row.update({
                "end_created_header_delta": end_tag["created_time_header"] - note["created_time"],
                "end_created_a_delta": end_tag["created_time_a"] - note["created_time"],
                "end_created_b_delta": end_tag["created_time_b"] - note["created_time"],
                "end_extra_nonzero": end_tag["extra_time_candidate"] != 0,
                "end_extra_delta_to_note_modified": (
                    end_tag["extra_time_candidate"] - note["modified_time"]
                    if end_tag["extra_time_candidate"]
                    else None
                ),
            })
        if note_bytes:
            note_last_u32 = struct.unpack_from("<I", note_bytes, len(note_bytes) - 4)[0]
            row["tail_post_hash_matches_note_last_u32"] = [
                record["value"] == note_last_u32
                for record in note.get("tail_records", ())
                if record["kind"] == "tail_post_hash_u32"
            ]
        media_deltas = [
            record["time_candidate"] - note["modified_time"]
            for record in media.get("records", ())
            if record.get("time_candidate") is not None
        ]
        if media_deltas:
            row["media_time_min_delta_to_note_modified"] = min(media_deltas)
            row["media_time_max_delta_to_note_modified"] = max(media_deltas)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    return {
        "count": len(rows),
        "end_created_header_exact": sum(1 for row in rows if row["end_created_header_delta"] == 0),
        "end_created_a_exact": sum(1 for row in rows if row["end_created_a_delta"] == 0),
        "end_created_b_exact": sum(1 for row in rows if row["end_created_b_delta"] == 0),
        "end_created_a_deltas": dict(sorted(Counter(row["end_created_a_delta"] for row in rows).items())),
        "end_created_b_deltas": dict(sorted(Counter(row["end_created_b_delta"] for row in rows).items())),
        "end_extra_nonzero": sum(1 for row in rows if row["end_extra_nonzero"]),
        "tail_post_hash_copy_checks": {
            "total": sum(len(row["tail_post_hash_matches_note_last_u32"]) for row in rows),
            "matched": sum(sum(row["tail_post_hash_matches_note_last_u32"]) for row in rows),
        },
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
    print(f"time rows={summary['count']}")
    print(
        "end_tag created exact: "
        f"header={summary['end_created_header_exact']} "
        f"a={summary['end_created_a_exact']} b={summary['end_created_b_exact']}"
    )
    print(f"end_created_a_deltas={summary['end_created_a_deltas']}")
    print(f"end_created_b_deltas={summary['end_created_b_deltas']}")
    print(f"end_extra_nonzero={summary['end_extra_nonzero']}")
    print(f"tail_post_hash_copy_checks={summary['tail_post_hash_copy_checks']}")
    for row in rows:
        print(
            f"  {row['file']:<58} "
            f"a_delta={row['end_created_a_delta']} b_delta={row['end_created_b_delta']} "
            f"extra_delta_mod={row['end_extra_delta_to_note_modified']} "
            f"media_delta_mod={row['media_time_min_delta_to_note_modified']}..{row['media_time_max_delta_to_note_modified']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
