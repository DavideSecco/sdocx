"""Corpus diagnostics for media/mediaInfo.dat record tails.

The tail structure is decoded as
`[u16 ref_count][u64 modified_time][u8 is_attached]`. This tool explores how
the media modified-time value relates to other container times.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_media_info, load_note  # noqa: E402
from pysdocx.note import parse_note_metadata  # noqa: E402


def _paths(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")) + sorted(path.glob("*/note.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def _zip_us(info: zipfile.ZipInfo | None) -> int | None:
    if info is None:
        return None
    return int(datetime(*info.date_time, tzinfo=timezone.utc).timestamp() * 1_000_000)


def collect_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in _paths(paths):
        media = list_media_info(path, verify_hash=True)
        note = parse_note_metadata(load_note(path))
        if media is None or note is None:
            continue
        with zipfile.ZipFile(path) as z:
            infos = {info.filename: info for info in z.infolist()}
        for record in media["records"]:
            info = infos.get(record["archive_name"])
            rows.append({
                "file": path.name,
                "media_index": record["media_index"],
                "name": record["name"],
                "extension": Path(record["name"]).suffix.lower() or "(none)",
                "ref_count": record["ref_count"],
                "modified_time": record["modified_time"],
                "is_attached": record["is_attached"],
                "tail_len": len(bytes.fromhex(record["raw_tail"])),
                "note_created_delta": record["modified_time"] - note["created_time"],
                "note_modified_delta": record["modified_time"] - note["modified_time"],
                "zip_time_delta": (
                    record["modified_time"] - _zip_us(info)
                    if _zip_us(info) is not None
                    else None
                ),
                "zip_size": info.file_size if info else None,
                "sha256_matches": record.get("sha256_matches"),
            })
    return rows


def summarize(rows: list[dict]) -> dict:
    by_file = []
    for file_name in sorted({row["file"] for row in rows}):
        file_rows = [row for row in rows if row["file"] == file_name]
        latest = max(file_rows, key=lambda row: row["modified_time"])
        by_file.append({
            "file": file_name,
            "count": len(file_rows),
            "ref_counts": dict(sorted(Counter(row["ref_count"] for row in file_rows).items())),
            "extensions": dict(sorted(Counter(row["extension"] for row in file_rows).items())),
            "latest_media_index": latest["media_index"],
            "latest_extension": latest["extension"],
            "latest_delta_to_note_modified": latest["note_modified_delta"],
        })
    return {
        "count": len(rows),
        "tail_lengths": dict(sorted(Counter(row["tail_len"] for row in rows).items())),
        "is_attached": dict(sorted(Counter(row["is_attached"] for row in rows).items())),
        "ref_counts": dict(sorted(Counter(row["ref_count"] for row in rows).items())),
        "ref_count_extension_matrix": {
            str(ref_count): dict(sorted(counter.items()))
            for ref_count, counter in sorted(_matrix(rows, "ref_count", "extension").items())
        },
        "exact_matches": {
            "note_created": sum(1 for row in rows if row["note_created_delta"] == 0),
            "note_modified": sum(1 for row in rows if row["note_modified_delta"] == 0),
            "zip_time": sum(1 for row in rows if row["zip_time_delta"] == 0),
        },
        "by_file": by_file,
    }


def _matrix(rows: list[dict], key: str, value: str) -> dict[object, Counter]:
    matrix: dict[object, Counter] = defaultdict(Counter)
    for row in rows:
        matrix[row[key]][row[value]] += 1
    return matrix


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
    print(f"media tail rows={summary['count']}")
    print(
        f"tail_lengths={summary['tail_lengths']} "
        f"is_attached={summary['is_attached']} ref_counts={summary['ref_counts']}"
    )
    print(f"ref_count_extension_matrix={summary['ref_count_extension_matrix']}")
    print(f"exact_matches={summary['exact_matches']}")
    for row in summary["by_file"]:
        print(
            f"  {row['file']:<58} n={row['count']:<3} ref_counts={row['ref_counts']} "
            f"latest={row['latest_media_index']}:{row['latest_extension']} "
            f"delta_to_note_modified={row['latest_delta_to_note_modified']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
