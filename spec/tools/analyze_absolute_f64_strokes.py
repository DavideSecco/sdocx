"""Look for absolute-f64 stroke coordinate candidates.

Known stroke coordinates are delta-compressed. This diagnostic searches stroke
object blobs for alternate payloads shaped as absolute `(f64 x, f64 y)` pairs,
either with a nearby `u32 count` prefix or as an aligned raw run. It does not
change the parser; it just reports candidates worth reverse-engineering.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_pages, load_page  # noqa: E402
from pysdocx.page import (  # noqa: E402
    OBJECT_BBOX_OFFSET,
    STROKE_OBJECT_BASE_TOTAL_SIZE,
    _iter_objects,
    parse_page,
    parse_stroke,
)


def _paths(paths: list[Path]) -> list[Path]:
    out = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.glob("*.sdocx")) + sorted(path.glob("*/note.sdocx")))
        elif path.suffix == ".sdocx":
            out.append(path)
    return sorted(dict.fromkeys(out))


def _inside_ratio(points: list[tuple[float, float]], bbox: tuple[float, float, float, float], tol: float = 8.0) -> float:
    if not points:
        return 0.0
    x0, y0, x1, y1 = bbox
    return sum(1 for x, y in points if x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol) / len(points)


def _read_pairs(blob: bytes, off: int, count: int) -> list[tuple[float, float]] | None:
    end = off + count * 16
    if end > len(blob):
        return None
    points = []
    for i in range(count):
        x, y = struct.unpack_from("<dd", blob, off + i * 16)
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        if not (-100000.0 <= x <= 100000.0 and -100000.0 <= y <= 100000.0):
            return None
        points.append((x, y))
    return points


def _bbox_span(points: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def _candidate(blob: bytes, points_off: int, count: int, bbox: tuple[float, float, float, float]) -> dict | None:
    points = _read_pairs(blob, points_off, count)
    if points is None or len(points) < 2:
        return None
    ratio = _inside_ratio(points, bbox)
    span_x, span_y = _bbox_span(points)
    if ratio < 0.8 or (span_x < 0.5 and span_y < 0.5):
        return None
    return {
        "points_off": points_off,
        "point_count": count,
        "inside_bbox_ratio": ratio,
        "span": [span_x, span_y],
        "first_points": [[x, y] for x, y in points[:5]],
    }


def _delta_decoder_is_suspicious(page_data: bytes, obj: dict) -> bool:
    header = obj.get("header")
    if not header:
        return True
    extra_len = max(header["total_size"] - STROKE_OBJECT_BASE_TOTAL_SIZE, 0)
    stroke_off = obj["blob_off"] + OBJECT_BBOX_OFFSET
    current = parse_stroke(page_data, stroke_off, extra_len, "current")
    shifted = parse_stroke(page_data, stroke_off, extra_len, "shifted")
    return not ((current and current["fits_bbox"]) or (shifted and shifted["fits_bbox"]))


def collect_candidates(paths: list[Path], scan_all: bool = False) -> tuple[list[dict], dict]:
    candidates = []
    stats = {"stroke_objects": 0, "scanned_objects": 0, "skipped_delta_consistent": 0}
    for path in _paths(paths):
        for page_name in list_pages(path):
            page_data = load_page(path, page_name)[1]
            page = parse_page(page_data)
            for layer in page["layers"]:
                for obj in _iter_objects(layer["objects"]):
                    if obj["raw_type"] != 1 or obj.get("bbox") is None:
                        continue
                    stats["stroke_objects"] += 1
                    if not scan_all and not _delta_decoder_is_suspicious(page_data, obj):
                        stats["skipped_delta_consistent"] += 1
                        continue
                    stats["scanned_objects"] += 1
                    blob = page_data[obj["blob_off"]:obj["end"]]
                    bbox = obj["bbox"]
                    header_total_size = (obj.get("header") or {}).get("total_size") or 0
                    found = []
                    # Count-prefixed form: <u32 count><count x f64 pair>.
                    for off in range(header_total_size, max(header_total_size, len(blob) - 4), 2):
                        count = struct.unpack_from("<I", blob, off)[0]
                        if not (2 <= count <= 512):
                            continue
                        cand = _candidate(blob, off + 4, count, bbox)
                        if cand is not None:
                            cand["kind"] = "u32_count_prefixed"
                            cand["count_off"] = off
                            found.append(cand)
                    # Raw aligned run, used only as a weak fallback diagnostic.
                    for off in range(header_total_size, max(header_total_size, len(blob) - 16 * 3), 8):
                        max_count = min(64, (len(blob) - off) // 16)
                        for count in range(min(max_count, 16), 2, -1):
                            cand = _candidate(blob, off, count, bbox)
                            if cand is not None:
                                cand["kind"] = "raw_aligned_run"
                                found.append(cand)
                                break
                    if found:
                        found.sort(key=lambda item: (item["point_count"], item["inside_bbox_ratio"]), reverse=True)
                        best = found[0]
                        candidates.append({
                            "file": path.name,
                            "page_uuid": page["uuid"],
                            "object_off": obj["off"],
                            "blob_size": obj["size"],
                            "header_total_size": (obj.get("header") or {}).get("total_size"),
                            "field_flags": (obj.get("header") or {}).get("field_flags"),
                            "bbox": list(bbox),
                            **best,
                        })
    return candidates, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*", help="files or directories (default: samples/)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all", action="store_true", help="scan every stroke, including delta-consistent ones")
    args = parser.parse_args()
    candidates, stats = collect_candidates(args.paths or [Path("samples")], scan_all=args.all)
    if args.json:
        print(json.dumps({"count": len(candidates), "stats": stats, "candidates": candidates}, indent=2, ensure_ascii=False))
        return 0
    print(f"absolute-f64 stroke candidates={len(candidates)} stats={stats}")
    for row in candidates[:50]:
        print(
            f"  {row['file']:<58} page={row['page_uuid'][:8]} obj=0x{row['object_off']:x} "
            f"kind={row['kind']} off={row['points_off']} n={row['point_count']} "
            f"ratio={row['inside_bbox_ratio']:.2f} span={row['span']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
