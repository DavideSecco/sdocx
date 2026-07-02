"""Parse typed ("keyboard") rich text from a document's note.note file.

Samsung Notes stores typed text at the container level in `note.note`, NOT in the per-page
`.page` files (page 5 of the benchmark has zero stroke/element records — its text lives here).
The text is one UTF-16LE field prefixed by a `[u32][u32 char_count]` header, and its styling is
a list of TLV run markers `18 00 <tag> 00 | pad | u32 start | u32 end | u32 value | u32 enabled`
whose start/end index into that text field. Confirmed on the benchmark (note.note): bold=tag
0x05 over "Grassetto", italic=0x06 over "corsivo", underline=0x07 over "sottolineato", and color
= tag 0x01 whose per-run `value`/`enabled` u32 is an 0xAARRGGBB color ("testorosso"→0xFFFF3636
red, body default→dark gray). This mirrors the per-page TLV logic in crates/sdocx/src/page.rs
(tlv_color / collect_style_runs), applied to note.note instead of a page record.

Not yet decoded here (approximated by the renderer): strikethrough ("cancellato") and the
list/todolist paragraph markers, which are not emitted as 0x18-00 run markers.
"""

import struct

STYLE_MARKER_PREFIX = b"\x18\x00"
BOLD_TAG = 0x05
ITALIC_TAG = 0x06
UNDERLINE_TAG = 0x07
COLOR_TAG = 0x01
FONT_TAG = 0x03

# A run marker is: 18 00 <tag_lo> <tag_hi> | 00 00 | u32 start | u32 end | u32 value | u32 enabled
RUN_START_OFF = 6
RUN_END_OFF = 10
RUN_VALUE_OFF = 14
RUN_ENABLED_OFF = 18
RUN_MARKER_LEN = 22

MIN_TEXT_FIELD_CHARS = 16


# 0xFFFC (object replacement char) anchors inline objects inside the text and must be kept as
# part of the field, or it splits the run and throws off the style-run indices.
def _is_printable_unit(unit: int) -> bool:
    return unit == 0x0A or unit == 0xFFFC or 0x20 <= unit <= 0xD7FF


# Leading characters that are field padding, not body text (newlines + object anchors).
_LEADING_PAD = "\n￼"


def _find_text_field(data: bytes) -> tuple[int, str] | None:
    """Return `(start_byte, text)` of the longest printable UTF-16LE run (the typed-text field).

    The run markers index characters from the start of this field (which begins with the
    header-inserted leading newlines), so the field start is char index 0 for the run offsets.
    """
    best_start = best_len = 0
    i = 0
    n = len(data)
    while i + 2 <= n:
        if _is_printable_unit(struct.unpack_from("<H", data, i)[0]):
            j = i
            while j + 2 <= n and _is_printable_unit(struct.unpack_from("<H", data, j)[0]):
                j += 2
            if (j - i) // 2 > best_len:
                best_start, best_len = i, (j - i) // 2
            i = j + 2
        else:
            i += 2
    if best_len < MIN_TEXT_FIELD_CHARS:
        return None
    text = data[best_start : best_start + best_len * 2].decode("utf-16-le", errors="replace")
    return best_start, text


def _style_runs(data: bytes, tag: int, text_len: int) -> list[tuple[int, int, int, int]]:
    """All `(start, end, value, enabled)` run markers for `tag` whose range is within the text."""
    marker = STYLE_MARKER_PREFIX + bytes([tag & 0xFF, tag >> 8])
    runs = []
    off = data.find(marker)
    while off != -1:
        if off + RUN_MARKER_LEN <= len(data):
            start = struct.unpack_from("<I", data, off + RUN_START_OFF)[0]
            end = struct.unpack_from("<I", data, off + RUN_END_OFF)[0]
            value = struct.unpack_from("<I", data, off + RUN_VALUE_OFF)[0]
            enabled = struct.unpack_from("<I", data, off + RUN_ENABLED_OFF)[0]
            if start < end <= text_len:
                runs.append((start, end, value, enabled))
        off = data.find(marker, off + 1)
    return runs


def parse_typed_text(note_bytes: bytes) -> dict | None:
    """Extract the typed rich text from `note.note`.

    Returns a dict with the body text and per-run styles mapped to body-text coordinates:
    `{text, runs: [{start, end, bold, italic, underline}], colors: [{start, end, color}], font_size}`.
    `text` has the header's leading newlines stripped; run/color offsets are relative to it.
    Returns None if no text field is found.
    """
    field = _find_text_field(note_bytes)
    if field is None:
        return None
    _, raw = field
    raw_len = len(raw)

    lead = len(raw) - len(raw.lstrip(_LEADING_PAD))
    body = raw[lead:]

    def rebase(start: int, end: int) -> tuple[int, int] | None:
        s, e = start - lead, end - lead
        if e <= 0 or s >= len(body):
            return None
        return max(s, 0), min(e, len(body))

    runs: list[dict] = []
    for tag, key in ((BOLD_TAG, "bold"), (ITALIC_TAG, "italic"), (UNDERLINE_TAG, "underline")):
        for start, end, _value, enabled in _style_runs(note_bytes, tag, raw_len):
            if enabled:  # explicit "on" run; Samsung emits a matching "off" run we can ignore
                rb = rebase(start, end)
                if rb:
                    runs.append({"start": rb[0], "end": rb[1], "style": key})

    colors: list[dict] = []
    for start, end, value, enabled in _style_runs(note_bytes, COLOR_TAG, raw_len):
        argb = enabled  # for the color tag the trailing u32 is the 0xAARRGGBB color
        r, g, b = (argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF
        rb = rebase(start, end)
        if rb is not None and (argb >> 24) == 0xFF:
            colors.append({"start": rb[0], "end": rb[1], "color": (r, g, b)})

    font_size = None
    font_runs = _style_runs(note_bytes, FONT_TAG, raw_len)
    if font_runs:
        raw_f = struct.pack("<I", font_runs[0][3])
        candidate = struct.unpack("<f", raw_f)[0]
        if candidate == candidate and 4.0 <= candidate <= 200.0:
            font_size = candidate

    return {"text": body, "runs": runs, "colors": colors, "font_size": font_size}


# Table cells also live in note.note (not the page). Each cell is preceded by a 10-byte marker:
# `06 00 <u16 kind> 00 00 <u32 char_count>`, immediately after which its UTF-16LE text begins.
# The cell's bottom-left corner in page coords is the f64 pair at `marker - 16` (x) and
# `marker - 8` (y). Confirmed on benchmark page 73920cee's kind 0x95 cells ("Cell1,1"...)
# and on Associationpages...'s kind 0x8d sparse table ("c11", "c13", "c21"...).
TABLE_CELL_PREFIX = b"\x06\x00"
TABLE_CELL_KINDS = frozenset({0x8D, 0x95, 0xCD})
TABLE_CELL_MARKER_LEN = 10
TABLE_ANCHOR_X_BACK = 16
TABLE_ANCHOR_Y_BACK = 8


def _cluster(values: list[float], tol: float = 8.0) -> list[float]:
    """Collapse near-equal coordinates (grid lines) into single averaged values."""
    clusters: list[list[float]] = []
    for v in sorted(values):
        if clusters and v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters]


def parse_tables(note_bytes: bytes) -> list[dict]:
    """Extract tables from `note.note`.

    Returns a list of `{rows, cols, bbox, x_edges, y_edges, cells}` where each cell is
    `{row, col, text, anchor}` (anchor = bottom-left corner in page coords). Cells are read in
    document (row-major) order; the grid is reconstructed by clustering the cell anchors into
    column/row lines (Samsung tables use equal-sized cells). Returns [] if no table cells found.
    """
    cells = []
    off = note_bytes.find(TABLE_CELL_PREFIX)
    while off != -1:
        if off + TABLE_CELL_MARKER_LEN > len(note_bytes):
            break
        kind = struct.unpack_from("<H", note_bytes, off + 2)[0]
        char_count = struct.unpack_from("<I", note_bytes, off + 6)[0]
        if kind not in TABLE_CELL_KINDS or not (1 <= char_count <= 512):
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue

        text_start = off + TABLE_CELL_MARKER_LEN
        text_end = text_start + char_count * 2
        if text_end > len(note_bytes):
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue
        end = text_start
        units = []
        while end + 2 <= text_end:
            unit = struct.unpack_from("<H", note_bytes, end)[0]
            if not (0x20 <= unit <= 0xD7FF):
                break
            units.append(unit)
            end += 2
        if not units:
            off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)
            continue

        anchor = None
        if off - TABLE_ANCHOR_X_BACK >= 0:
            x = struct.unpack_from("<d", note_bytes, off - TABLE_ANCHOR_X_BACK)[0]
            y = struct.unpack_from("<d", note_bytes, off - TABLE_ANCHOR_Y_BACK)[0]
            if 0 <= x <= 3000 and 0 <= y <= 4000:
                anchor = (x, y)
        if anchor is not None:
            cells.append({"text": "".join(chr(u) for u in units), "anchor": anchor})
        off = note_bytes.find(TABLE_CELL_PREFIX, off + 1)

    anchored = [c for c in cells if c["anchor"] is not None]
    if not anchored:
        return []

    xs = _cluster([c["anchor"][0] for c in anchored])
    ys = _cluster([c["anchor"][1] for c in anchored])
    cols, rows = len(xs), len(ys)
    if cols < 1 or rows < 1:
        # Grid didn't reconstruct cleanly — return the cells with their raw anchors only.
        return [{"rows": rows, "cols": cols, "bbox": None, "x_edges": xs, "y_edges": ys, "cells": cells}]

    col_w = (xs[-1] - xs[0]) / (cols - 1) if cols > 1 else 0.0
    row_h = (ys[-1] - ys[0]) / (rows - 1) if rows > 1 else 0.0
    # Anchors are bottom-left corners: xs[0] is the table's left edge; the row anchors are bottoms,
    # so the table top is one row-height above the first row's anchor.
    x_edges = [xs[0] + i * col_w for i in range(cols + 1)]
    y_edges = [ys[0] - row_h + i * row_h for i in range(rows + 1)]
    for cell in cells:
        x, y = cell["anchor"]
        cell["col"] = min(range(cols), key=lambda i: abs(xs[i] - x))
        cell["row"] = min(range(rows), key=lambda i: abs(ys[i] - y))
    return [
        {
            "rows": rows,
            "cols": cols,
            "bbox": (x_edges[0], y_edges[0], x_edges[-1], y_edges[-1]),
            "x_edges": x_edges,
            "y_edges": y_edges,
            "cells": cells,
        }
    ]
