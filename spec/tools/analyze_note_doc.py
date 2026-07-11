"""Cross-check the structural `note.note` parser against the marker scans.

`pysdocx.note_doc.parse_note_doc` parses the whole `note.note` member as one
sequential structure whose hard gate is positional: it must consume bytes
`0 .. len(note)-32` exactly (the trailing 32 bytes are the already-validated
`sha256(note.note[:-32])`), so every intermediate field boundary must be
correct for the parse to land on the hash by construction.

This diagnostic runs that parser over the corpus and cross-checks it against
the independent pysdocx marker scans:

* header fields vs `parse_note_metadata`;
* title/body `text_core::Common` frame text vs the title scan and
  `_find_text_field`;
* structural span records vs the `18 00 <tag> 00` / `14 00 14 00` TLV scans
  (excluding zero-length spans, which the scan cannot see);
* nested table-cell Common frames vs `parse_tables` cell texts;
* inline-object `position` vs the U+FFFC anchors in the body text;
* voice recordings vs the voice-clip tail scans and mediaInfo records;
* pen info names vs the pen-preload path scans.

Field names/scheme cross-referenced from squ1dd13/sdocx2pdf (MIT) —
`sdocx/src/note_doc.rs`, `sdocx/src/page/object/text_core.rs` — used as
independent evidence, re-validated here on the local corpus.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pysdocx.container import list_media_info, load_note  # noqa: E402
from pysdocx.note import (  # noqa: E402
    _find_text_field,
    _style_runs,
    parse_note_metadata,
    parse_tables,
)
from pysdocx.note_doc import (  # noqa: E402
    FIELD_NAMES,
    NoteDocParseError,
    note_doc_common_frames,
    note_doc_tables,
    parse_note_doc,
)


def _span_key_set(spans: list[dict], span_type: int) -> set[tuple[int, int]]:
    return {(s["start"], s["end"]) for s in spans if s["span_type"] == span_type}


def cross_check(path: Path, doc: dict, note: bytes) -> dict:
    meta = parse_note_metadata(note)
    frames = note_doc_common_frames(note, doc)
    checks: dict = {}

    # Header agreement with the existing pysdocx reference parse.
    checks["header_matches_pysdocx"] = bool(
        meta
        and meta["offset_to_data"] == doc["flex_offset"]
        and meta["flags"] == doc["property_flags"]
        and meta["meta_flags"] == doc["field_flags"]
        and meta["format_version"] == doc["format_version"]
        and meta["note_id"] == doc["id"]
        and meta["file_revision"] == doc["file_revision"]
        and meta["created_time"] == doc["created_time_us"]
        and meta["modified_time"] == doc["modified_time_us"]
        and meta["width"] == doc["width"]
        and meta["height"] == doc["height"]
        and meta["title_size"] == doc["title_size"]
    )

    # Title: the Common frame inside the title Text blob must carry meta title.
    title_frame = frames["title"]
    checks["title_text_matches"] = (
        title_frame is not None and title_frame["text"] == meta["title"]
        if meta and meta.get("title")
        else None
    )

    # Body: the Common frame inside the body Text blob must carry the raw text
    # field (leading pad included) that _find_text_field locates globally.
    body_frame = frames["body"]
    field = _find_text_field(note)
    if field is not None:
        checks["body_text_matches"] = (
            body_frame is not None and body_frame["text"] == field[1])
    else:
        checks["body_text_matches"] = None

    # Structural spans vs TLV marker scans (raw coordinates, whole-file scan).
    # Two known scan blind spots make raw set equality wrong to demand:
    #  * the scan requires start < end, so zero-length structural spans are
    #    invisible to it;
    #  * the scan sweeps the whole file, so table-cell Common frames (nested
    #    in the body inline object, cell-local coordinates) also match when
    #    their range happens to fit inside the body text length.
    # We therefore compare non-zero-length structural spans of the body frame
    # PLUS all nested cell frames against the scan.
    span_agreements = {}
    if body_frame is not None and field is not None:
        raw_len = len(field[1])
        for tag, label in ((1, "color"), (3, "font_size"), (5, "bold"),
                           (6, "italic"), (7, "underline"), (17, "highlight")):
            scan = {(s, e) for s, e, _v, _en in _style_runs(note, tag, raw_len)}
            structural = set()
            for frame in [body_frame, *frames["cells"]]:
                structural |= {
                    key for key in _span_key_set(frame["spans"], tag)
                    if key[0] < key[1] <= raw_len
                }
            span_agreements[label] = {
                "structural": len(structural),
                "scan": len(scan),
                "structural_subset_of_scan": structural <= scan,
                "equal": structural == scan,
            }
    checks["span_agreements"] = span_agreements
    checks["body_frame"] = {
        k: body_frame[k]
        for k in ("off", "frame_size", "margins", "gravity", "sections", "inline")
    } if body_frame else None
    if body_frame:
        checks["body_span_type_hist"] = dict(Counter(
            s["span_type"] for s in body_frame["spans"]))
        checks["body_paragraph_type_hist"] = dict(Counter(
            p["paragraph_type"] for p in body_frame["paragraphs"]))
        checks["body_span_record_sizes"] = dict(Counter(
            (s["span_type"], s["record_size"]) for s in body_frame["spans"]))

    # Inline objects: their `position` must be the index of a U+FFFC object
    # replacement char in the frame text.
    if body_frame is not None:
        anchors = [i for i, ch in enumerate(body_frame["text"]) if ch == "￼"]
        objs = (body_frame["inline"] or {}).get("objects", [])
        checks["inline_object_types"] = [o["object_type"] for o in objs]
        checks["inline_positions_match_anchors"] = (
            sorted(o["position"] for o in objs) == anchors if objs else None
        )

    # Table cells: every non-main Common frame in the body blob is a table cell
    # (the structural parser is authoritative). The legacy marker scan is a
    # non-contradicting corroborator — it may recover fewer cells (it clusters
    # anchors globally and so cannot separate several tables in one note, e.g.
    # the 4x3 styled family), but it must never invent a cell text the
    # structural parser does not have. So we require the scan's cell-text
    # multiset to be a sub-multiset of the structural one.
    if body_frame is not None:
        scan_cell_texts = Counter(
            c["text"]
            for table in parse_tables(note)
            for c in table["cells"]
        )
        struct_cell_texts = Counter(f["text"] for f in frames["cells"])
        checks["cell_frame_count"] = len(frames["cells"])
        checks["cell_texts_match_table_scan"] = (
            not (scan_cell_texts - struct_cell_texts)
            if frames["cells"] or scan_cell_texts
            else None
        )

    # Full structural parse of every type-22 table inline object, cross-checked
    # against the marker scan (parse_tables): grid shape, per-position cell
    # text, the scan's anchor == the last cell-outline path point, stored
    # column widths == the anchor-derived column pitch, and the table bbox ==
    # the union of the cell bboxes.
    tables_structural = []
    try:
        structural_tables = note_doc_tables(note, doc)
    except NoteDocParseError as exc:
        structural_tables = None
        checks["table_structural_error"] = f"{type(exc).__name__}: {exc}"
    if structural_tables:
        scan_tables = parse_tables(note)
        # The scan clusters cell anchors globally, so it can only align to the
        # structural tables positionally when it reconstructed the same number
        # of tables. On a multi-table note it collapses them into one grid; its
        # per-table corroboration is then inapplicable (the structural parser's
        # byte-exact parse + ground-truth PDF stand on their own).
        scan_aligned = len(scan_tables) == len(structural_tables)
        for i, t in enumerate(structural_tables):
            scan = scan_tables[i] if scan_aligned else None
            scan_by_pos = {
                (c["row"], c["col"]): c for c in (scan or {}).get("cells", ())
            }
            cell_rows = t["rows"]
            # The scan corroborates but is not authoritative: where it recovers a
            # cell at a position, its text/anchor must agree with the structural
            # parser (non-contradiction); a cell the scan did not recover is not
            # counted against agreement.
            texts_ok = anchors_ok = True
            for r, row in enumerate(cell_rows):
                for c in row["cells"]:
                    sc = scan_by_pos.get((r, c["col"]))
                    if sc is None:
                        continue
                    # scan texts stop at the first non-BMP-printable char
                    if not c["frame"]["text"].startswith(sc["text"]):
                        texts_ok = False
                    if c["outline"][-1] != sc["anchor"]:
                        anchors_ok = False
            col_x = [c["bbox"][0] for c in cell_rows[0]["cells"]]
            pitch_ok = all(
                abs((col_x[k + 1] - col_x[k]) - t["col_widths"][k]) < 0.5
                for k in range(len(col_x) - 1)
            )
            union = (
                min(c["bbox"][0] for r in cell_rows for c in r["cells"]),
                min(c["bbox"][1] for r in cell_rows for c in r["cells"]),
                max(c["bbox"][2] for r in cell_rows for c in r["cells"]),
                max(c["bbox"][3] for r in cell_rows for c in r["cells"]),
            )
            # The wrap bbox describes the cell layout's *shape* and horizontal
            # position exactly. Its Y-origin, however, can differ from the cell
            # bboxes': cells are usually page-local (dy ~ 0.5) but on the
            # column-width-edited table they carry a document-stacked Y origin
            # (dy = a whole-page-height multiple). So compare width/height + X
            # exactly and record the Y offset rather than forcing Y to match.
            cell_bbox_dy = round(union[1] - t["bbox"][1], 2)
            bbox_ok = (
                abs(union[0] - t["bbox"][0]) < 1.0
                and abs(union[2] - t["bbox"][2]) < 1.0
                and abs((union[3] - union[1]) - (t["bbox"][3] - t["bbox"][1])) < 1.0
            )
            tables_structural.append({
                "n_rows": t["n_rows"], "n_cols": t["n_cols"],
                "cells": sum(len(r["cells"]) for r in cell_rows),
                "grid_matches_scan": bool(
                    scan and scan["rows"] == t["n_rows"]
                    and scan["cols"] == t["n_cols"]),
                "texts_match_scan": texts_ok,
                "anchors_are_outline_points": anchors_ok,
                "widths_match_pitch": pitch_ok,
                "bbox_is_cell_union": bbox_ok,
                "cell_bbox_dy": cell_bbox_dy,
                "page_width_matches_note": t["page_width"] == doc["width"],
                "ts_us": (t["ts1_us"], t["ts2_us"]),
                "col_widths": [round(w, 2) for w in t["col_widths"]],
                "row_heights": [round(r["height"], 2) for r in cell_rows],
                "outer_borders": [
                    (f"{b['argb']:08x}", round(b["width"], 2),
                     round(b["radius_x"], 2), round(b["radius_y"], 2))
                    for b in t["outer_borders"]],
                "grid_borders": [
                    (f"{b['argb']:08x}", round(b["width"], 2),
                     round(b["radius_x"], 2), round(b["radius_y"], 2))
                    for b in t["grid_borders"]],
                "theme_fill_argb": f"{t['theme_fill_argb']:08x}",
            })
    checks["tables_structural"] = tables_structural

    # Voice recordings vs the tail-record scans.
    voice_checks = []
    scan_clips = [r for r in (meta or {}).get("tail_records", ())
                  if r.get("kind") == "voice_clip"]
    structural_voice = doc["fields"].get("voice_data", [])
    media = list_media_info(path) or {}
    media_by_index = {r["media_index"]: r for r in media.get("records", ())}
    for i, rec in enumerate(structural_voice):
        scan = scan_clips[i] if i < len(scan_clips) else {}
        media_rec = media_by_index.get(rec["file_id"])
        voice_checks.append({
            "name": rec["name"],
            "name_matches_scan": rec["name"] == scan.get("label"),
            "duration_matches_scan": rec["duration_str"] == scan.get("duration"),
            "file_id": rec["file_id"],
            "file_id_matches_scan_media_index":
                rec["file_id"] == scan.get("media_index_candidate"),
            "file_id_in_media_info": media_rec is not None,
            "media_name": media_rec.get("name") if media_rec else None,
            "precise_ms": rec["precise_duration_ms"],
            "precise_ms_matches_scan":
                rec["precise_duration_ms"] == scan.get("actual_duration_ms_candidate"),
            "event_count": len(rec["events"]),
        })
    checks["voice"] = voice_checks
    checks["voice_counts_match"] = len(structural_voice) == len(scan_clips)

    # Pen info vs the pen preload/style tail scans.
    pen_names_scan = {r.get("path") for r in (meta or {}).get("tail_records", ())
                      if r.get("kind") == "pen_preload_path"}
    pens = {}
    for key in ("compatible_last_pen_info", "last_pen_info"):
        pen = doc["fields"].get(key)
        if pen:
            pens[key] = {
                "name": pen["name"],
                "name_in_preload_scan": pen["name"] in pen_names_scan,
                "advanced_settings": pen["advanced_settings"],
                "size": pen["size"],
                "color": pen["color"],
            }
    checks["pens"] = pens

    # Attached files vs mediaInfo.
    attached = doc["fields"].get("attached_files")
    if attached is not None:
        checks["attached_files_in_media_info"] = all(
            f["file_id"] in media_by_index for f in attached)
    return checks


def collect(paths: list[Path]) -> dict:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.sdocx")))
        elif path.suffix == ".sdocx":
            files.append(path)
    files = sorted(dict.fromkeys(files))

    rows = []
    for path in files:
        note = load_note(path)
        if note is None:
            continue
        row: dict = {"file": path.name, "note_size": len(note)}
        try:
            doc = parse_note_doc(note)
            row["parse_ok"] = True
            row["landed_on_hash"] = doc["landed_on_hash"]
            row["doc"] = doc
            row["checks"] = cross_check(path, doc, note)
        except (NoteDocParseError, UnicodeDecodeError) as exc:
            row["parse_ok"] = False
            row["landed_on_hash"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    field_bit_hist: Counter = Counter()
    for row in rows:
        if row.get("parse_ok"):
            bits = row["doc"]["field_flags"]
            for b, name in FIELD_NAMES.items():
                if bits >> b & 1:
                    field_bit_hist[f"{b}:{name}"] += 1

    summary = {
        "files": len(rows),
        "parse_ok": sum(1 for r in rows if r.get("parse_ok")),
        "landed_on_hash": sum(1 for r in rows if r.get("landed_on_hash")),
        "header_matches_pysdocx": sum(
            1 for r in rows if r.get("checks", {}).get("header_matches_pysdocx")),
        "gap_sizes": dict(Counter(
            r["doc"]["gap_size"] for r in rows if r.get("parse_ok"))),
        "property_flags_values": dict(Counter(
            r["doc"]["property_flags"] for r in rows if r.get("parse_ok"))),
        "field_bit_hist": dict(field_bit_hist),
        "title_text_matches": sum(
            1 for r in rows if r.get("checks", {}).get("title_text_matches")),
        "title_text_surfaces": sum(
            1 for r in rows if r.get("checks", {}).get("title_text_matches") is not None),
        "body_text_matches": sum(
            1 for r in rows if r.get("checks", {}).get("body_text_matches")),
        "body_text_surfaces": sum(
            1 for r in rows if r.get("checks", {}).get("body_text_matches") is not None),
        "span_families_equal": Counter(),
        "span_families_total": Counter(),
        "inline_objects_with_anchor_match": sum(
            1 for r in rows
            if r.get("checks", {}).get("inline_positions_match_anchors")),
        "inline_object_surfaces": sum(
            1 for r in rows
            if r.get("checks", {}).get("inline_positions_match_anchors") is not None),
        "cell_texts_match_table_scan": sum(
            1 for r in rows
            if r.get("checks", {}).get("cell_texts_match_table_scan")),
        "tables_structural": sum(
            len(r.get("checks", {}).get("tables_structural", ())) for r in rows),
        # Gate on the structural self-consistency checks plus scan
        # non-contradiction. `grid_matches_scan` is scan-completeness (the scan
        # can't split multi-table notes), so it is reported but not gated.
        "tables_structural_all_checks": sum(
            1 for r in rows
            for t in r.get("checks", {}).get("tables_structural", ())
            if t["texts_match_scan"]
            and t["anchors_are_outline_points"] and t["widths_match_pitch"]
            and t["bbox_is_cell_union"] and t["page_width_matches_note"]),
        "table_cells_structural": sum(
            t["cells"] for r in rows
            for t in r.get("checks", {}).get("tables_structural", ())),
        "table_structural_errors": sum(
            1 for r in rows
            if r.get("checks", {}).get("table_structural_error")),
        "cell_text_surfaces": sum(
            1 for r in rows
            if r.get("checks", {}).get("cell_texts_match_table_scan") is not None),
        "voice_records": sum(
            len(r.get("checks", {}).get("voice", ())) for r in rows),
        "voice_all_fields_match": sum(
            1 for r in rows for v in r.get("checks", {}).get("voice", ())
            if v["name_matches_scan"] and v["duration_matches_scan"]
            and v["file_id_matches_scan_media_index"] and v["file_id_in_media_info"]),
    }
    for row in rows:
        for label, agreement in row.get("checks", {}).get("span_agreements", {}).items():
            if agreement["scan"] or agreement["structural"]:
                summary["span_families_total"][label] += 1
                if agreement["equal"]:
                    summary["span_families_equal"][label] += 1
    summary["span_families_equal"] = dict(summary["span_families_equal"])
    summary["span_families_total"] = dict(summary["span_families_total"])
    return {"summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="*", help="files or directories (default: samples/)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect(args.paths or [Path("samples")])
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    s = report["summary"]
    print(f"files={s['files']} parse_ok={s['parse_ok']} landed_on_hash={s['landed_on_hash']} "
          f"header_matches_pysdocx={s['header_matches_pysdocx']}")
    print(f"gap_sizes={s['gap_sizes']} property_flags={s['property_flags_values']}")
    print(f"field bits: {s['field_bit_hist']}")
    print(f"title common-frame text match: {s['title_text_matches']}/{s['title_text_surfaces']}")
    print(f"body common-frame text match:  {s['body_text_matches']}/{s['body_text_surfaces']}")
    print(f"span families equal-to-scan: {s['span_families_equal']} of {s['span_families_total']}")
    print(f"inline objects anchor-match: {s['inline_objects_with_anchor_match']}/{s['inline_object_surfaces']} "
          f"cell texts match table scan: {s['cell_texts_match_table_scan']}/{s['cell_text_surfaces']}")
    print(f"tables structural: {s['tables_structural_all_checks']}/{s['tables_structural']} "
          f"all-checks (cells={s['table_cells_structural']}, "
          f"errors={s['table_structural_errors']})")
    print(f"voice records: {s['voice_records']} all-fields-match={s['voice_all_fields_match']}")
    for row in report["rows"]:
        if not row.get("parse_ok"):
            print(f"  FAIL {row['file']}: {row.get('error')}")
            continue
        doc = row["doc"]
        checks = row["checks"]
        print(f"  OK {row['file']} landed_on_hash={row['landed_on_hash']} "
              f"gap={doc['gap_size']} gap_pair={doc['gap_u32_pair']} "
              f"fields={sorted(doc['fields'])}")
        if checks.get("body_frame"):
            bf = checks["body_frame"]
            print(f"     body frame off={bf['off']} margins={bf['margins']} "
                  f"gravity={bf['gravity']} sections={len(bf['sections'])} "
                  f"inline={'None' if bf['inline'] is None else bf['inline']['present']}")
            print(f"     span types={checks.get('body_span_type_hist')} "
                  f"paragraph types={checks.get('body_paragraph_type_hist')}")
        for label, agreement in checks.get("span_agreements", {}).items():
            if not agreement["equal"] and (agreement["scan"] or agreement["structural"]):
                print(f"     SPAN-DIFF {label}: structural={agreement['structural']} "
                      f"scan={agreement['scan']} subset={agreement['structural_subset_of_scan']}")
        for v in checks.get("voice", ()):
            print(f"     VOICE {v['name']!r} file_id={v['file_id']} media={v['media_name']!r} "
                  f"name_ok={v['name_matches_scan']} dur_ok={v['duration_matches_scan']} "
                  f"ms_ok={v['precise_ms_matches_scan']} events={v['event_count']}")
        for t in checks.get("tables_structural", ()):
            print(f"     TABLE {t['n_rows']}x{t['n_cols']} cells={t['cells']} "
                  f"grid_ok={t['grid_matches_scan']} texts_ok={t['texts_match_scan']} "
                  f"anchors_ok={t['anchors_are_outline_points']} "
                  f"widths_ok={t['widths_match_pitch']} bbox_ok={t['bbox_is_cell_union']} "
                  f"page_w_ok={t['page_width_matches_note']}")
            print(f"       widths={t['col_widths']} heights={t['row_heights']} "
                  f"outer={t['outer_borders'][0]} grid={t['grid_borders'][0]} "
                  f"theme_fill={t['theme_fill_argb']}")
        if checks.get("table_structural_error"):
            print(f"     TABLE-ERROR {checks['table_structural_error']}")
        for key, pen in checks.get("pens", {}).items():
            print(f"     PEN {key}: name={pen['name']!r} preload_scan_hit={pen['name_in_preload_scan']} "
                  f"size={pen['size']:.2f} color={pen['color']} adv={pen['advanced_settings']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
