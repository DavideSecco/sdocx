"""Corpus diagnostics for marker-scanned note.note tail records.

This explores semantic candidates in the already-bounded tail records without
promoting marker scans into Kaitai.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_media_info, load_note  # noqa: E402
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
        note = load_note(path)
        meta = parse_note_metadata(note) if note else None
        if note is None or meta is None:
            continue
        media = list_media_info(path) or {"records": []}
        media_by_index = {record["media_index"]: record for record in media["records"]}
        for idx, record in enumerate(meta.get("tail_records", [])):
            row = dict(record)
            row["file"] = path.name
            row["idx"] = idx
            if row["kind"] == "tail_post_hash_u32":
                row["matches_note_trailing_u32"] = row["value"] == struct.unpack_from("<I", note, len(note) - 4)[0]
            if row["kind"] == "voice_clip":
                media_record = media_by_index.get(row.get("media_index_candidate"))
                row["media_name"] = media_record.get("name") if media_record else None
                row["media_info_time_candidate"] = media_record.get("time_candidate") if media_record else None
                row["media_time_delta"] = (
                    row.get("media_time_candidate") - media_record.get("time_candidate")
                    if media_record and row.get("media_time_candidate") is not None
                    else None
                )
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    path_hints: dict[str, Counter] = defaultdict(Counter)
    prelude_pairs = Counter()
    style_shapes = Counter()
    voice_rows = []
    post_hash = []
    by_file: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_file[row["file"]].append(row)

    for row in rows:
        if row["kind"] == "pen_preload_path":
            path_hints[row["path"]][row.get("param_hint")] += 1
        elif row["kind"] == "pen_style_tail":
            style_shapes[
                (
                    round(row.get("width", -1.0), 3),
                    row.get("argb"),
                    row.get("param"),
                    tuple(row.get("raw_u32", ())),
                )
            ] += 1
        elif row["kind"] == "voice_clip":
            voice_rows.append({
                "file": row["file"],
                "label": row.get("label"),
                "media_index": row.get("media_index_candidate"),
                "media_name": row.get("media_name"),
                "duration_ms_display": row.get("duration_ms_display"),
                "actual_duration_ms_candidate": row.get("actual_duration_ms_candidate"),
                "media_time_delta": row.get("media_time_delta"),
            })
        elif row["kind"] == "tail_post_hash_u32":
            post_hash.append({
                "file": row["file"],
                "value": row["value"],
                "matches_note_trailing_u32": row.get("matches_note_trailing_u32"),
            })

    for file_name, file_rows in by_file.items():
        file_rows = sorted(file_rows, key=lambda row: (row["off"], row["end"], row["kind"]))
        for i, row in enumerate(file_rows):
            if row["kind"] != "pen_preload_path":
                continue
            prev = file_rows[i - 1] if i else {}
            prelude_pairs[
                (
                    row["path"].split(".")[-1],
                    row.get("param_hint"),
                    prev.get("kind"),
                    prev.get("param"),
                    tuple(prev.get("prefix_u32", prev.get("raw_u32", ()))),
                    tuple(prev.get("trailing_u32", ())),
                )
            ] += 1

    return {
        "kinds": dict(sorted(Counter(row["kind"] for row in rows).items())),
        "path_param_hints": {
            path: {str(k): v for k, v in sorted(counter.items(), key=lambda item: str(item[0]))}
            for path, counter in sorted(path_hints.items())
        },
        "preload_path_previous_record_shapes": [
            {
                "path_tail": key[0],
                "path_param_hint": key[1],
                "previous_kind": key[2],
                "previous_param": key[3],
                "previous_prefix_or_raw_u32": list(key[4]),
                "previous_trailing_u32": list(key[5]),
                "count": count,
            }
            for key, count in sorted(prelude_pairs.items(), key=lambda item: (item[0][0], str(item[0][1]), str(item[0][2]), item[1]))
        ],
        "pen_style_tail_shapes": [
            {
                "width": key[0],
                "argb": key[1],
                "param": key[2],
                "raw_u32": list(key[3]),
                "count": count,
            }
            for key, count in sorted(style_shapes.items(), key=lambda item: (item[0][0], item[0][1] or "", item[0][2] or "", item[0][3]))
        ],
        "voice_clips": voice_rows,
        "tail_post_hash_u32": post_hash,
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
    print(f"note tail kinds={summary['kinds']}")
    print("path param hints:")
    for path, hints in summary["path_param_hints"].items():
        print(f"  {path:<58} {hints}")
    print("voice clips:")
    for row in summary["voice_clips"]:
        print(
            f"  {row['file']:<58} media={row['media_index']} {row['media_name']} "
            f"display={row['duration_ms_display']} actual={row['actual_duration_ms_candidate']} "
            f"media_time_delta={row['media_time_delta']}"
        )
    print("tail_post_hash_u32:")
    for row in summary["tail_post_hash_u32"]:
        print(f"  {row['file']:<58} value=0x{row['value']:08x} trailing_copy={row['matches_note_trailing_u32']}")
    print(f"preload/path previous-record shapes={len(summary['preload_path_previous_record_shapes'])}")
    print(f"pen_style_tail shapes={len(summary['pen_style_tail_shapes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
