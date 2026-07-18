#!/usr/bin/env python
"""Regenerate `note_tables_pysdocx.json` — the byte-exact table parity fixture.

Dumps `pysdocx.note_doc.note_doc_tables` for every corpus sample that carries a
structural table, so `crates/sdocx/tests/note_tables.rs` can assert the Rust
port (`note_doc::note_tables`) matches pysdocx field-for-field.

Run from the repo root with the uv venv:
    .venv/bin/python crates/sdocx/tests/fixtures/gen_note_tables.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pysdocx.note_doc import note_doc_tables, parse_note_doc

REPO = Path(__file__).resolve().parents[4]
SAMPLES = REPO / "samples"
OUT = Path(__file__).resolve().parent / "note_tables_pysdocx.json"


def border(b: dict) -> list:
    return [b["argb"], round(b["width"], 4), round(b["radius_x"], 4), round(b["radius_y"], 4)]


def bbox(r) -> list:
    return [round(v, 6) for v in r]


def dump_table(t: dict) -> dict:
    cells = []
    for row in t["rows"]:
        for c in row["cells"]:
            cells.append({
                "row": next(i for i, rr in enumerate(t["rows"]) if rr is row),
                "col": c["col"],
                "bbox": bbox(c["bbox"]),
                "uuid": c["uuid"],
                "version": c["version"],
                "styled": bool(c["styled"]),
                "fill_argb": c["fill_argb"],
                "text": c["frame"]["text"],
                "n_spans": len(c["frame"]["spans"]),
            })
    return {
        "uuid": t["uuid"],
        "bbox": bbox(t["bbox"]),
        "page_width": t["page_width"],
        "table_index": t["table_index"],
        "n_rows": t["n_rows"],
        "n_cols": t["n_cols"],
        "col_widths": [round(w, 4) for w in t["col_widths"]],
        "row_heights": [round(r["height"], 4) for r in t["rows"]],
        "col_width_min": [round(w, 4) for w in t["col_width_min"]],
        "col_width_max": [round(w, 4) for w in t["col_width_max"]],
        "table_width_max": round(t["table_width_max"], 4),
        "outer_borders": [border(b) for b in t["outer_borders"]],
        "grid_borders": [border(b) for b in t["grid_borders"]],
        "theme_fill_argb": t["theme_fill_argb"],
        "cells": cells,
    }


def main() -> None:
    result: dict[str, list] = {}
    for path in sorted(SAMPLES.glob("*.sdocx")) + sorted(SAMPLES.glob("*/note.sdocx")):
        try:
            with zipfile.ZipFile(path) as z:
                note = z.read("note.note")
        except (KeyError, zipfile.BadZipFile):
            continue
        doc = parse_note_doc(note)
        tables = note_doc_tables(note, doc)
        if tables:
            result[path.name] = [dump_table(t) for t in tables]
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    total = sum(len(v) for v in result.values())
    cells = sum(len(t["cells"]) for v in result.values() for t in v)
    print(f"wrote {OUT} — {len(result)} samples, {total} tables, {cells} cells")


if __name__ == "__main__":
    main()
