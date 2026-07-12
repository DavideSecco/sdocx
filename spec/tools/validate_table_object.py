"""Cross-check the Kaitai table-object spec against pysdocx across the corpus.

For every type-22 inline object in every corpus note, parse the object body
with both the generated `sdocx_table_object` Kaitai parser and
`pysdocx.note_doc.parse_table_object`, and assert the decoded fields match —
wrap, geometry, rows/cells, per-cell fill + nested Common frame (text, spans,
paragraphs), and the style tail (border blocks, width constraints, theme fill).

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_table_object.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_table_object import SdocxTableObject  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.container import load_note  # noqa: E402
from pysdocx.note_doc import (  # noqa: E402
    NoteDocParseError,
    note_doc_common_frames,
    parse_note_doc,
    parse_table_object,
)


def _rect(k) -> tuple:
    return (k.x0, k.y0, k.x1, k.y1)


def _path_points(path_rec) -> list[tuple]:
    return [(op.x, op.y) for op in path_rec.body.ops if op.op != 6]


def _borders(block) -> list[dict]:
    return [{"argb": e.argb, "width": e.width,
             "radius_x": e.radius_x, "radius_y": e.radius_y}
            for e in block.body.entries]


def _frame_diffs(kf, ref: dict) -> list[str]:
    """Compare a Kaitai common_frame against a pysdocx parse_common_frame dict."""
    out = []
    if kf.text_utf16 != ref["text"]:
        out.append("frame text")
    kspans = [{"record_size": s.record_size, "span_type": s.span_type,
               "start": s.start, "end": s.end,
               "interval_type": s.interval_type, "extra": s.extra.hex()}
              for s in kf.spans]
    if kspans != ref["spans"]:
        out.append("frame spans")
    kparas = [{"record_size": p.record_size, "paragraph_type": p.paragraph_type,
               "start": p.start, "end": p.end, "extra": p.extra.hex()}
              for p in kf.paragraphs]
    if kparas != ref["paragraphs"]:
        out.append("frame paragraphs")
    if list(kf.margins) != ref["margins"] or kf.gravity != ref["gravity"]:
        out.append("frame margins/gravity")
    if [(s.a, s.b) for s in kf.sections] != ref["sections"]:
        out.append("frame sections")
    inline = ref["inline"]
    if inline is not None and (kf.inline_present != inline["present"]
                               or kf.inline_zero != inline["zero_field"]):
        out.append("frame inline header")
    return out


def _diffs(blob: bytes, ref: dict) -> list[str]:
    k = SdocxTableObject.from_bytes(blob)
    out = []

    w = k.wrap.body
    if (w.uuid != ref["uuid"] or w.version != ref["version"]
            or w.ts1_us != ref["ts1_us"] or w.ts2_us != ref["ts2_us"]
            or _rect(w.bbox) != ref["bbox"]
            or w.page_width != ref["page_width"]):
        out.append("wrap")
    if [(p.x, p.y) for p in k.midpoints.body.points] != ref["text_midpoints"]:
        out.append("midpoints")
    if _path_points(k.outline.body.path) != ref["text_outline"]:
        out.append("outline")

    c = k.content
    if (c.head.hex() != ref["content_head_hex"]
            or c.content_u16 != ref["content_u16"]):
        out.append("content head")
    if (c.n_rows != ref["n_rows"] or c.n_cols != ref["n_cols"]
            or list(c.col_widths) != ref["col_widths"]):
        out.append("grid shape")

    for r, (krow, row) in enumerate(zip(c.rows, ref["rows"])):
        rb = krow.body
        if rb.height != row["height"] or rb.row_index != r:
            out.append(f"row {r}")
        for kcell, cell in zip(rb.cells, row["cells"]):
            cb = kcell.body
            tag = f"cell {r},{cell['col']}"
            if (cb.col_index != cell["col"] or cb.styled != cell["styled"]
                    or cb.fill_argb != cell["fill_argb"]
                    or _rect(cb.bbox) != cell["bbox"]):
                out.append(tag)
            if (cb.cwrap.body.uuid != cell["uuid"]
                    or cb.cwrap.body.version != cell["version"]
                    or _rect(cb.cwrap.body.bbox) != cell["bbox"]):
                out.append(f"{tag} wrap")
            if [(p.x, p.y) for p in cb.cmid.body.points] != cell["midpoints"]:
                out.append(f"{tag} midpoints")
            if _path_points(cb.coutline.body.path) != cell["outline"]:
                out.append(f"{tag} outline")
            out += [f"{tag} {d}"
                    for d in _frame_diffs(cb.coutline.body.frame, cell["frame"])]

    if _rect(c.tail_bbox) != ref["bbox"]:
        out.append("tail bbox")
    if _borders(c.outer_borders) != ref["outer_borders"]:
        out.append("outer borders")
    if _borders(c.grid_borders) != ref["grid_borders"]:
        out.append("grid borders")
    if (list(c.col_width_min) != ref["col_width_min"]
            or list(c.col_width_max) != ref["col_width_max"]
            or c.table_width_max != ref["table_width_max"]):
        out.append("width constraints")
    if c.theme_fill_argb != ref["theme_fill_argb"]:
        out.append("theme fill")
    return out


def diffs_for_note(note: bytes) -> list[tuple[int, list[str]]]:
    """(count, per-table diffs) for every type-22 object in one note.note.

    Returns a list of `(body_off, diff-list)` — one entry per table object,
    empty diff-list meaning the Kaitai parse matches pysdocx exactly.
    """
    try:
        doc = parse_note_doc(note)
        frames = note_doc_common_frames(note, doc)
    except NoteDocParseError:
        return []
    body = frames["body"]
    if body is None or not body.get("inline"):
        return []
    blob = note[doc["body_off"]:doc["body_off"] + doc["body_size"]]
    out = []
    for obj in body["inline"]["objects"]:
        if obj["object_type"] != 22:
            continue
        ref = parse_table_object(
            blob, obj["body_off"], obj["obj_size"], doc["format_version"])
        d = _diffs(blob[obj["body_off"]:obj["body_off"] + obj["obj_size"]], ref)
        out.append((obj["body_off"], d))
    return out


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        note = load_note(sample)
        if note is None:
            continue
        for body_off, d in diffs_for_note(note):
            if d:
                failures += 1
                print(f"FAIL  {sample.name} table@{body_off}: {d}")
            else:
                ok += 1
    print(f"\n{ok} table objects matched, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
