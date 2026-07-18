"""Rendering for parsed .sdocx pages — matplotlib/Pillow live here only.

The core parser (container/page/note/ink) stays free of heavy dependencies; all
of numpy/matplotlib/Pillow are imported in this module. The rendering logic was
lifted verbatim from notebooks/03_ink.ipynb (cells `render`, `b93e132d`,
`d9411e7e`) so `python -m pysdocx render` produces the same images the notebook
did. `render_document` is the high-level entry point (one figure per page).

Install the optional deps with `pip install sdocx[render]`.
"""

import io
import math
import re
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import Ellipse, FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath
from PIL import Image

from pysdocx.container import (
    list_pages,
    load_media_by_index,
    load_note,
    load_page_with_bg,
    raster_media_indices,
)
from pysdocx.ink import color_hex
from pysdocx.note import parse_tables, parse_typed_text  # noqa: F401 (legacy corroborator)
from pysdocx.note_doc import (
    note_doc_tables,
    note_table_grid,
    parse_note_doc,
    table_cell_style,
)
from pysdocx.page import GRID_ORIGIN, GRID_SPACING, OXFORD_MARGIN_COLOR, page_background_color, parse_page

MAX_PRESSURE = 1400.0
DEFAULT_INK = "#ffffff"
# Blue-gray of the Samsung rule/grid/dot templates. Deliberately DARKER than the GT-photo value
# (grid ~#d3dae8, dots ~#b7bfce there) at the user's request (2026-07-10): the true-to-photo tint
# is too faint to read on screen. Kept in sync with opensdocx lib.rs GRID_COLOR/DOT_COLOR.
GRID_COLOR = "#a6afca"
DOT_COLOR = "#8f98b0"
TEXT_DEFAULT_COLOR = (37, 37, 37)  # body default; ≈ the dark page bg, so we contrast it below
TODO_DONE_COLOR = (150, 150, 150)
TABLE_LINE_COLOR = "#8a8f9a"

# Page-coordinate units per unit of decoded paragraph space-before/after (note.py tags 0x08/0x09).
# ⚠ HEURISTIC: the stored values are decoded, while this scale is fitted against the typed-text
# GT. The controlled 2026-07-13 samples ground font/blank advances exactly; the mixed heading GT
# leaves this small independent conversion at 5.0 (best fit; former eyeballed value 4.9).
PARA_SPACE_UNIT = 5.0

# Typed-text layout geometry (page coordinates). x0/y0 = top-left text anchor; line_h = body line
# pitch (matches the GT grid at 11pt); fontpt = base point size.
TYPED_TEXT_X0 = 64
TYPED_TEXT_Y0 = 80
TYPED_TEXT_FONTPT = 17
TYPED_TEXT_LINE_H = 66
# Retained as the legacy text-box/default function argument; document-body blank rows use the
# active newline font through `_typed_note_advance` below.
TYPED_TEXT_BLANK_H = 66
# Samsung PDF ground truth exposes the exact typed-note transform: stored font size → PDF font is
# *5/3, PDF → page units is *8/3, and the default line-spacing multiplier is 1.35. Therefore the
# default baseline pitch is raw_font_size * 6; explicit line_spacing replaces 1.35. Blank lines
# retain the font size carried by their newline. The decoded Common body margins are [16,10,16,10]
# in the same logical font unit, so the vertical content band removes 10 * 40/9 at both ends.
TYPED_TEXT_FONT_TO_PAGE = 40.0 / 9.0
TYPED_TEXT_DEFAULT_LINE_SPACING = 1.35
TYPED_TEXT_VERTICAL_MARGIN = 10.0 * TYPED_TEXT_FONT_TO_PAGE
# Samsung's PDF uses Roboto; the workbench/app normally resolve generic sans-serif to a wider
# host font. Horizontally condense document-body glyph metrics/drawing to the measured PDF width.
TYPED_TEXT_GLYPH_WIDTH_SCALE = 0.96
# Hanging-list columns at stored size 11, measured from both Allsamsungnotes PDF + in-app GT.
TYPED_TEXT_NUMBER_BODY_INDENT = 80.0
TYPED_TEXT_LIST_BODY_INDENT = 116.0
TYPED_TEXT_BULLET_MARKER_INDENT = 40.0
TYPED_TEXT_TODO_MARKER_INDENT = 24.0
# Checkbox controls impose a taller row than 11pt text alone. This remains a render calibration:
# the old GT directly measures consecutive todo pitches at 77.76 and 75.99 page units.
TYPED_TEXT_TODO_MIN_H = (77.76 + 75.99) / 2.0

# ⚠ HEURISTIC: text-box frame_midpoints describe the outer rotated frame, but Samsung lays text
# out inside a smaller inner frame. Keeping the decoded anchor fixed and shrinking only the logical
# wrap width matches the current GT better for shallow rotations; near-vertical boxes keep the full
# projected width because their current three-column wrap matches the GT sample.
TEXT_BOX_FRAME_WRAP_INSET = 18.0

# Named backgrounds accepted by render_document/CLI (`--bg dark|white`).
BG_DARK = "#252525"
BG_WHITE = "#ffffff"
NAMED_BG = {"dark": BG_DARK, "white": BG_WHITE}


def _contrast_ink(bg_color):
    """Pick a legible default-ink color for the given background.

    On the (default) dark page background this returns white — identical to the
    notebook — so the default-ink fallback below is unchanged. On a light
    background it returns black so `--bg white` doesn't draw invisible ink.
    """
    try:
        r, g, b = (int(bg_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return DEFAULT_INK
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else DEFAULT_INK


def rasterize_pdf_page(pdf_bytes, page_index, target_width):
    """Rasterize one page of an embedded template / imported PDF to an RGBA numpy array,
    scaled so its width is `target_width` px (aspect preserved).

    Returns None if pypdfium2 is unavailable or the page can't be rendered — the caller then
    draws no background, the same graceful degradation as before rasterization existed. Uses
    pdfium, the same engine the Rust/Tauri app targets (`pdfium-render`), so this workbench and
    the shipped renderer rasterize identically. This is faithful rasterization of embedded
    artwork, not a calibrated heuristic — the (media index, page index) link it renders is the
    decoded `page_pdf_template` reference.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
        if page_index < 0 or page_index >= len(doc):
            return None
        page = doc[page_index]
        pdf_w, _ = page.get_size()
        if pdf_w <= 0:
            return None
        bitmap = page.render(scale=target_width / pdf_w)
        return np.asarray(bitmap.to_pil().convert("RGBA"))
    except Exception:
        return None


def draw_grid(ax, width, height, spacing=GRID_SPACING, origin=GRID_ORIGIN, color=GRID_COLOR, lw=0.6):
    """Draw the squared-paper template: light vertical + horizontal lines every `spacing`
    page units, spanning the whole page (0..width, 0..height). `origin` is the page-coord
    position of a grid line on each axis (the template has a ~44px top margin, so vertical
    lines start at x=0 but horizontal ones start ~44px down) — measured from the GT photos."""
    xs = np.arange(origin[0] % spacing, width + 0.5, spacing)
    ys = np.arange(origin[1] % spacing, height + 0.5, spacing)
    segments = [((x, 0.0), (x, height)) for x in xs] + [((0.0, y), (width, y)) for y in ys]
    ax.add_collection(LineCollection(segments, colors=color, linewidths=lw, zorder=0.5))


def draw_lines(ax, width, height, spacing, origin=GRID_ORIGIN, color=GRID_COLOR, lw=0.6):
    """Draw the "Lined" template: horizontal rules only, every `spacing` page units."""
    ys = np.arange(origin[1] % spacing, height + 0.5, spacing)
    segments = [((0.0, y), (width, y)) for y in ys]
    ax.add_collection(LineCollection(segments, colors=color, linewidths=lw, zorder=0.5))


def draw_dots(ax, width, height, row_spacing, col_spacing, origin=GRID_ORIGIN, color=DOT_COLOR, size=3.0):
    """Draw the "Dot" template: a lattice of dots. Unlike the grid, row/col pitch genuinely
    differ (DOT_SPACING_BY_ID in pysdocx.page) — this is not a square lattice."""
    xs = np.arange(origin[0] % col_spacing, width + 0.5, col_spacing)
    ys = np.arange(origin[1] % row_spacing, height + 0.5, row_spacing)
    xx, yy = np.meshgrid(xs, ys)
    ax.scatter(xx.ravel(), yy.ravel(), s=size, c=color, marker="o", linewidths=0, zorder=0.5)


def draw_oxford(ax, width, height, line_spacing, margin_x, origin=GRID_ORIGIN,
                 color=GRID_COLOR, margin_color=OXFORD_MARGIN_COLOR, lw=0.6, margin_lw=1.0):
    """Draw the "Oxford" template: horizontal rules at their own (tighter) pitch, plus a single
    vertical margin rule in a light red — the classic ruled-with-margin school-notebook layout."""
    ys = np.arange(origin[1] % line_spacing, height + 0.5, line_spacing)
    segments = [((0.0, y), (width, y)) for y in ys]
    ax.add_collection(LineCollection(segments, colors=color, linewidths=lw, zorder=0.5))
    ax.plot([margin_x, margin_x], [0.0, height], color=margin_color, lw=margin_lw, zorder=0.5)


def oriented_corners(points):
    """Reconstruct the (possibly rotated) box corners of the rounded-rect from its 4 stored
    edge-midpoints: corner_i = M_i + M_{i+1} - centroid. For an unrotated shape these are just the
    axis-aligned bbox corners. Only the rounded-rect still needs this (its outline path is
    degenerate); every other primitive now draws from its real decoded outline."""
    m = np.asarray(points, dtype=float)
    center = m.mean(axis=0)
    n = len(m)
    return [m[i] + m[(i + 1) % n] - center for i in range(n)]


def ellipse_from_points(points):
    """Center, width, height and rotation (deg) of an ellipse from its 8 boundary points
    (opposite points pt0/pt4 and pt2/pt6 are the axis endpoints). Rotation is 0 when unrotated."""
    p = np.asarray(points, dtype=float)
    center = p.mean(axis=0)
    axis_a, axis_b = p[0] - p[4], p[2] - p[6]
    angle = math.degrees(math.atan2(axis_a[1], axis_a[0]))
    return center, float(np.hypot(*axis_a)), float(np.hypot(*axis_b)), angle


def _path_from_outline_ops(outline_ops, closed):
    """Build a matplotlib Path straight from the shape's raw (tag, points) segments
    (pysdocx.page.decode_outline), so a CubicBezierTo segment (tag 4) draws as a
    true parametric curve (Path.CURVE4) instead of the fixed-16-point-per-segment
    sampled approximation `points`/flatten_outline uses. Only called when the
    outline actually contains a curve — see the caller."""
    verts, codes = [], []
    for tag, seg in outline_ops:
        if tag == 1:  # MoveTo
            verts.append(seg[0])
            codes.append(MplPath.MOVETO)
        elif tag == 2:  # LineTo
            verts.append(seg[0])
            codes.append(MplPath.LINETO)
        elif tag == 4:  # CubicBezierTo: 2 control points + end point
            verts.extend(seg)
            codes.extend([MplPath.CURVE4] * 3)
    if closed and verts:
        verts.append(verts[0])
        codes.append(MplPath.CLOSEPOLY)
    return MplPath(verts, codes)


def render_shape(ax, shape, bg_color, default_ink=DEFAULT_INK):
    """Draw one inserted shape from its decoded true outline (pysdocx.parse_shapes).

    Almost every shape (triangle/rect/hexagon/rhombus/trapezoid/pentagon/star/cross/heart and
    freeform) is drawn straight from its real, already-rotated / DOF-deformed outline points, so
    no canonical reconstruction is needed. Only the ellipse (from its 8 boundary points) and the
    rounded-rect (oriented box + rounded corners) keep a dedicated branch, since their stored
    outline path is degenerate. Line/arrow objects draw a segment plus an arrowhead at each end
    that carries one (`head_start`/`head_end`). `width` scales the line width; `closed` controls
    whether freeform curves are closed.
    """
    r, g, b = shape["color"]
    color = f"#{r:02x}{g:02x}{b:02x}"
    if color == bg_color:
        color = default_ink
    lw = max((shape.get("width") or 6.35) / 2.5, 1.0)
    kind = shape.get("type", "polygon")
    pts = shape["points"]
    closed = shape.get("closed", True)
    patch_kw = dict(fill=False, edgecolor=color, lw=lw, zorder=2)

    if kind == "ellipse":
        center, w, h, angle = ellipse_from_points(pts)
        ax.add_patch(Ellipse(center, w, h, angle=angle, **patch_kw))
    elif kind == "rounded_rect":
        corners = oriented_corners(pts)
        center = np.mean(corners, axis=0)
        w = float(np.hypot(*(corners[0] - corners[3])))
        h = float(np.hypot(*(corners[2] - corners[3])))
        angle = math.degrees(math.atan2((corners[0] - corners[3])[1], (corners[0] - corners[3])[0]))
        pad = min(w, h) * 0.25
        patch = FancyBboxPatch((center[0] - w / 2 + pad, center[1] - h / 2 + pad),
                               w - 2 * pad, h - 2 * pad, boxstyle=f"round,pad={pad}", **patch_kw)
        patch.set_transform(mtransforms.Affine2D().rotate_deg_around(center[0], center[1], angle) + ax.transData)
        ax.add_patch(patch)
    elif kind == "arrow":  # line/arrow tool: a segment with an optional arrowhead at each end
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        head_start = shape.get("head_start", False)
        head_end = shape.get("head_end", False)
        style = {(True, True): "<|-|>", (False, True): "-|>", (True, False): "<|-"}.get(
            (head_start, head_end), "-"
        )
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=2,
                    arrowprops=dict(arrowstyle=style, color=color, lw=lw, mutation_scale=8 + lw * 3))
    else:  # polygons + heart + cross + freeform: draw the real outline
        outline_ops = shape.get("outline_ops")
        # Only heart/freeform_smooth actually carry a CubicBezierTo segment — draw
        # those as a true Bezier (matches the OpenSdocx Rust/canvas renderer, which
        # does the same, so the two stay comparable at any zoom). Every other shape
        # here is an all-LineTo path; keep the plain polyline, unchanged, so the
        # well-established majority of shapes gets zero visual footprint from this.
        has_curve = outline_ops and any(tag == 4 for tag, _ in outline_ops)
        if has_curve:
            path = _path_from_outline_ops(outline_ops, closed)
            ax.add_patch(PathPatch(path, fill=False, edgecolor=color, lw=lw, zorder=2))
        else:
            poly = list(pts) + ([pts[0]] if closed else [])
            ax.plot([q[0] for q in poly], [q[1] for q in poly], "-", color=color, linewidth=lw, zorder=2)


def _text_box_layout(box):
    """Anchor/wrap parameters for a text-box from its bbox + decoded rotation.

    Samsung stores the text-box angle as the same clockwise-positive f32 used by images, but the
    TEXT anchor itself is not always the bbox's top-left corner after rotation. Near-vertical
    boxes (≈90°/270°) visually start from the bbox's top-RIGHT/left edge respectively; anchoring
    every box at `(x0, y0)` mirrors the column order compared to the GT sample.

    If a rotated text box exposes decoded `frame_midpoints`, use those first: they are the stored
    edge-midpoints of the rotated frame, so projecting them onto the local text axes gives the true
    half-extents and the exact logical top-left origin before rotation. The bbox-only branch below
    is a fallback heuristic for cases where that geometry is unavailable.
    """
    x0, y0, x1, y1 = box["bbox"]
    angle_deg = (box.get("angle_deg") or 0.0) % 360.0
    box_w = max(x1 - x0 - 16, 1.0)
    box_h = max(y1 - y0 - 16, 1.0)
    frame_midpoints = box.get("frame_midpoints") or ()

    if frame_midpoints and angle_deg:
        cx = sum(px for px, _py in frame_midpoints) / len(frame_midpoints)
        cy = sum(py for _px, py in frame_midpoints) / len(frame_midpoints)
        theta = math.radians(angle_deg)
        ux, uy = math.cos(theta), math.sin(theta)
        vx, vy = -math.sin(theta), math.cos(theta)
        half_w = max(abs((px - cx) * ux + (py - cy) * uy) for px, py in frame_midpoints)
        half_h = max(abs((px - cx) * vx + (py - cy) * vy) for px, py in frame_midpoints)
        if half_w > 1.0 and half_h > 1.0:
            near_vertical = abs(angle_deg - 90.0) <= 15.0 or abs(angle_deg - 270.0) <= 15.0
            wrap_inset = 0.0 if near_vertical else min(TEXT_BOX_FRAME_WRAP_INSET, half_w - 1.0)
            return {
                "anchor_x": cx - ux * half_w - vx * half_h,
                "anchor_y": cy - uy * half_w - vy * half_h,
                "wrap_width": max(half_w * 2.0 - 2.0 * wrap_inset, 1.0),
                "wrap_inset": wrap_inset,
                "line_dir": 1.0,
            }

    vertical_wrap_w = min(box_w, max(box_h, box_h * 1.6))
    vertical_anchor_pad = min(max(box_h * 0.1, 20.0), 36.0)
    if abs(angle_deg - 90.0) <= 15.0:
        return {
            "anchor_x": x1 - vertical_anchor_pad,
            "anchor_y": y0 + 8,
            "wrap_width": vertical_wrap_w,
            "wrap_inset": 0.0,
            "line_dir": 1.0,
        }
    if abs(angle_deg - 270.0) <= 15.0:
        return {
            "anchor_x": x0 + vertical_anchor_pad,
            "anchor_y": y1 - 8,
            "wrap_width": vertical_wrap_w,
            "wrap_inset": 0.0,
            "line_dir": 1.0,
        }
    return {
        "anchor_x": x0 + 8,
        "anchor_y": y0 + 8,
        "wrap_width": box_w,
        "wrap_inset": 0.0,
        "line_dir": 1.0,
    }


def _group_sink_lines(sink):
    """Collapse `(x, y, seg, style, line_h)` sink records into visual lines.

    `_render_rich_text(..., sink=...)` emits one entry per rendered segment. For diagnostics we
    want the logical lines the wrapper produced, preserving the segment/style boundaries that made
    those lines. y is grouped with the same 0.01-page-unit tolerance used elsewhere for sink-based
    pagination.
    """
    lines: list[dict] = []
    by_y: dict[float, dict] = {}
    for x, y, seg, style, line_h in sink:
        key = round(y, 2)
        line = by_y.get(key)
        if line is None:
            line = {"y": y, "advance": line_h, "segments": []}
            by_y[key] = line
            lines.append(line)
        line["segments"].append({"x": x, "text": seg, "style": style})
        line["advance"] = max(line["advance"], line_h)
    for line in lines:
        line["segments"].sort(key=lambda seg: seg["x"])
        line["text"] = "".join(seg["text"] for seg in line["segments"])
    lines.sort(key=lambda line: line["y"])
    return lines


def debug_text_box_layout(box, page_size=(1600, 2262), figsize=(9, 12), default_ink=DEFAULT_INK):
    """Return the current heuristic layout decisions + wrapped lines for one text box.

    This is diagnostic output for reverse engineering, not a decoded-format API: `wrap_width`,
    `anchor_*`, `line_h` and `blank_h` all reflect the CURRENT renderer heuristics. The wrapped
    lines are collected via the same sink-based path used for typed-text pagination, so they show
    the exact logical line breaks the renderer is choosing before any rotation is applied.
    """
    layout = _text_box_layout(box)
    x0, y0, x1, y1 = box["bbox"]
    box_w = max(x1 - x0 - 16, 1.0)
    box_h = max(y1 - y0 - 16, 1.0)
    frame_midpoints = box.get("frame_midpoints") or ()
    fontpt = max((box.get("font_size") or 11.0) * 1.36, 12.0)
    line_h = max(fontpt * 3.2, 36.0)
    blank_h = max(fontpt * 2.0, 24.0)

    fig, ax = plt.subplots(figsize=figsize)
    try:
        ax.set_xlim(0, page_size[0])
        ax.set_ylim(page_size[1], 0)
        sink: list = []
        _render_rich_text(
            ax,
            box,
            x0=layout["anchor_x"],
            y0=layout["anchor_y"],
            max_width=layout["wrap_width"],
            line_h=line_h,
            blank_h=blank_h,
            fontpt=fontpt,
            default_ink=default_ink,
            angle_deg=box.get("angle_deg") or 0.0,
            line_dir=layout["line_dir"],
            sink=sink,
        )
    finally:
        plt.close(fig)

    heuristics = [
        "line_h and blank_h are renderer geometry heuristics derived from font size",
        "wrapped lines are the current renderer's hypothesis before rotation is applied",
    ]
    if frame_midpoints:
        heuristics.insert(
            0,
            "anchor_x/anchor_y and wrap_width are derived from decoded frame_midpoints projected onto the local text axes",
        )
        if layout.get("wrap_inset"):
            heuristics.insert(1, f"wrap_width is shrunk by renderer inner-frame inset {layout['wrap_inset']:.1f}")
        else:
            heuristics.insert(1, "near-vertical text boxes keep the full projected wrap width")
    else:
        heuristics.insert(0, "anchor_x/anchor_y come from _text_box_layout fallback logic, not from decoded frame geometry")
        heuristics.insert(1, "wrap_width is the current renderer fallback, not a decoded logical box width")

    return {
        "bbox_inner_w": box_w,
        "bbox_inner_h": box_h,
        "anchor_x": layout["anchor_x"],
        "anchor_y": layout["anchor_y"],
        "wrap_width": layout["wrap_width"],
        "line_dir": layout["line_dir"],
        "fontpt": fontpt,
        "line_h": line_h,
        "blank_h": blank_h,
        "heuristics": heuristics,
        "lines": _group_sink_lines(sink),
    }


def render_page(ax, strokes, bg_color, title=None, shapes=(), images=(), text_boxes=(),
                sticky_notes=(), page_size=None, template=None, default_ink=DEFAULT_INK,
                template_image=None):
    """Draw a parsed page (strokes, inserted shapes, imported images) onto a matplotlib Axes.

    `images` is a list of {"bbox": (x0, y0, x1, y1), "data": <image bytes>}. When `page_size`
    (width, height) is given, the axes are fixed to the whole page (not autoscaled to content)
    and, if `template` is a grid template, the squared background is drawn under everything.
    `template_image` is a pre-rasterised full-page RGBA background (numpy array) for a
    `kind: "pdf"` template — see `rasterize_pdf_page`; drawn to fill the page under everything.
    `default_ink` is the fallback color for strokes/shapes whose stored color matches the
    background (contrast against the page); it is white on a dark page, black on a light one.
    """
    ax.set_facecolor(bg_color)
    if page_size is not None:
        ax.set_xlim(0, page_size[0])
        ax.set_ylim(page_size[1], 0)  # y increases downward in page coords

    # Template background goes above the flat fill but below images/strokes.
    if page_size is not None and template is not None:
        kind = template["kind"]
        if kind == "grid":
            draw_grid(ax, page_size[0], page_size[1], spacing=template.get("spacing", GRID_SPACING))
        elif kind == "line" and "row_spacing" in template:
            draw_lines(ax, page_size[0], page_size[1], spacing=template["row_spacing"])
        elif kind == "dot" and "row_spacing" in template and "col_spacing" in template:
            draw_dots(ax, page_size[0], page_size[1],
                      row_spacing=template["row_spacing"], col_spacing=template["col_spacing"])
        elif kind == "oxford" and "line_spacing" in template:
            draw_oxford(ax, page_size[0], page_size[1],
                        line_spacing=template["line_spacing"], margin_x=template["margin_x"])
        elif kind in ("pdf", "image") and template_image is not None:
            # Academic multi-page / imported PDF: the background is an embedded media/….pdf page
            # (template["pdf_media_index"]/["pdf_page_index"]), pre-rasterised by the caller. The
            # PDF page is A4, the same aspect as the sdocx page, so it fills 0..w × 0..h upright:
            # origin="upper" puts image row 0 at the extent's `top` (y=0 = screen top, since the
            # y-axis is inverted below). If pypdfium2 is missing, template_image is None and no
            # background is drawn (graceful degradation).
            ax.imshow(template_image, extent=(0, page_size[0], page_size[1], 0),
                      origin="upper", aspect="auto", zorder=0.4)

    # Imported images go underneath everything else. The axis is y-inverted at
    # the end (page coords have y increasing downward), so use origin="lower"
    # with the natural extent to keep the picture itself upright.
    for im in images:
        x0, y0, x1, y1 = im["bbox"]
        # RGBA, not RGB: when a rotation transform is applied below, matplotlib's image resampler
        # has to sample outside the source array for the corners of the rotated bounding box (the
        # parts of the axis-aligned bbox the rotated rectangle doesn't cover) — with no alpha
        # channel those out-of-bounds samples render as opaque black. RGBA makes them transparent
        # instead, so the page background shows through the corners as expected.
        pic = np.asarray(Image.open(io.BytesIO(im["data"])).convert("RGBA"))
        artist = ax.imshow(pic, extent=(x0, x1, y0, y1), origin="lower", aspect="auto", zorder=1)
        angle_deg = im.get("angle_deg") or 0.0
        if angle_deg:
            # angle_deg is clockwise-positive on screen (see pysdocx.page.IMAGE_ANGLE_OFFSET).
            # rotate_deg_around is counterclockwise-positive in data space, but the y-axis is
            # inverted for the whole page (set_ylim(height, 0) below), which flips the apparent
            # rotation sense back to clockwise on screen — so the raw decoded angle is used as-is.
            # Pivot is the placement bbox's own center: bbox is the pre-rotation reference rect
            # (verified: its width/height match this same source image's unrotated placements).
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            artist.set_transform(mtransforms.Affine2D().rotate_deg_around(cx, cy, angle_deg) + ax.transData)

    for s in strokes:
        pts = s["points"]
        if len(pts) < 2:
            continue

        color = color_hex(s["color"])
        # A stroke whose decoded color matches the canvas exactly is using the
        # "default ink" indicator, not a deliberate same-as-background color —
        # fall back to a contrasting ink so it's actually visible.
        if color is None or color == bg_color:
            color = default_ink
        base_w = s["pen_width"] / 4
        pressures = s["pressures"]  # already normalized 0..1

        # The BGRA alpha byte is the pen's "intensità" (opacity) slider, 0-255.
        # Map it to a render opacity floored at 0.3 so even intensity 0 (alpha
        # ~3) stays visible, as it does in Samsung Notes, while 50/100 differ.
        opacity = 0.3 + 0.7 * (s["intensity"] / 255)

        pts_arr = np.array(pts)
        segments = np.stack([pts_arr[:-1], pts_arr[1:]], axis=1)

        # Only ink-pen-category tools (s["tapered"]) have pressure-sensitive
        # width (fountain/calligraphy-nib effect) — highlighters/markers are
        # flat felt tips and render at a constant width regardless of
        # per-point pressure.
        if s["tapered"] and len(pressures) >= len(pts) - 1:
            p_norm = np.clip(np.array(pressures[: len(pts) - 1]), 0, 1)
            widths = base_w * (0.3 + 0.7 * p_norm)
        else:
            widths = np.full(len(segments), base_w)

        lc = LineCollection(
            segments, linewidths=widths, colors=color, capstyle="round", alpha=opacity, zorder=2
        )
        ax.add_collection(lc)

    # Inserted shapes carry a decoded type code (pysdocx.parse_shapes): rectangle/square/cross/
    # trapezoid/ellipse/rounded-rect are drawn from their oriented box (rotation honored), regular
    # polygons/star from their vertices, arrows as a line + head, and freeform shapes open or closed
    # per `closed`. This replaces the earlier angular-vs-smooth angle heuristic.
    for sh in shapes:
        render_shape(ax, sh, bg_color, default_ink=default_ink)

    for box in text_boxes:
        if box["bbox"] is None:
            continue
        angle_deg = box.get("angle_deg") or 0.0
        layout = _text_box_layout(box)
        fontpt = max((box.get("font_size") or 11.0) * 1.36, 12.0)
        line_h = max(fontpt * 3.2, 36.0)
        blank_h = max(fontpt * 2.0, 24.0)
        _render_rich_text(
            ax,
            box,
            x0=layout["anchor_x"],
            y0=layout["anchor_y"],
            max_width=layout["wrap_width"],
            line_h=line_h,
            blank_h=blank_h,
            fontpt=fontpt,
            default_ink=default_ink,
            angle_deg=angle_deg,
            line_dir=layout["line_dir"],
        )

    # Sticky-note placements (scan_sticky_notes) aren't recursively rendered — a nested .sdocx
    # sub-document's contents aren't loaded here — just marked as a labeled box at its decoded
    # bbox so the attachment's existence and rough position are visible instead of silently
    # absent from the render (matches the "at least enumerate them" bar used for audio/images
    # elsewhere in this module).
    for note in sticky_notes:
        x0, y0, x1, y1 = note["bbox"]
        ax.add_patch(
            plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=default_ink,
                          lw=1.0, linestyle="--", zorder=3)
        )
        ax.text(x0 + 4, y0 + 4, f"sticky note (media {note['media_index']})", color=default_ink,
                fontsize=9, va="top", ha="left", zorder=3)

    if page_size is not None:
        # Fix the view to the whole page so the grid fills it and content sits in place.
        ax.set_xlim(0, page_size[0])
        ax.set_ylim(page_size[1], 0)  # y increases downward in page coords
    else:
        ax.autoscale()
        ax.invert_yaxis()
    ax.set_aspect("equal")
    if title is None:
        title = (
            f"{len(strokes)} strokes, {len(shapes)} shapes, {len(images)} images, "
            f"{sum(1 for s in strokes if s['color'])} colored, "
            f"{sum(1 for s in strokes if s['pressures'])} with pressure"
        )
    ax.set_title(title, color="white", fontsize=10)
    ax.tick_params(colors="gray")


def _char_styles(parsed):
    """Expand per-run styles into per-character style arrays."""
    n = len(parsed["text"])
    bold = [False] * n
    italic = [False] * n
    underline = [False] * n
    strike = [False] * n
    color = [None] * n
    highlight = [None] * n
    font_size = [None] * n
    for r in parsed["runs"]:
        for i in range(r["start"], min(r["end"], n)):
            if r["style"] == "bold":
                bold[i] = True
            elif r["style"] == "italic":
                italic[i] = True
            elif r["style"] == "underline":
                underline[i] = True
            elif r["style"] == "strikethrough":
                strike[i] = True
    for c in parsed["colors"]:
        if c["color"] != TEXT_DEFAULT_COLOR:  # default color is handled by the contrast fallback
            for i in range(c["start"], min(c["end"], n)):
                color[i] = c["color"]
    for h in parsed.get("highlights", ()):
        for i in range(h["start"], min(h["end"], n)):
            highlight[i] = h["color"]
    for f in parsed.get("font_sizes", ()):
        for i in range(f["start"], min(f["end"], n)):
            font_size[i] = f["font_size"]
    return bold, italic, underline, strike, color, highlight, font_size


def _measure_text(
    ax, renderer, inv, x, y, text, fontpt, bold, italic, angle_deg=0.0, width_scale=1.0
):
    probe = ax.text(
        x, y, text, fontsize=fontpt, va="top", ha="left",
        fontweight="bold" if bold else "normal",
        fontstyle="italic" if italic else "normal",
        alpha=0.0,
        rotation=-angle_deg if angle_deg else 0.0,
        rotation_mode="anchor",
    )
    corners = inv.transform(probe.get_window_extent(renderer).corners())
    probe.remove()
    if width_scale != 1.0:
        corners[:, 0] = x + (corners[:, 0] - x) * width_scale
    return corners


def _style_fontpt(style, fontpt):
    return (style[6] * 1.36) if style[6] else fontpt


def _rotate_point(x, y, origin_x, origin_y, angle_deg):
    if not angle_deg:
        return x, y
    return mtransforms.Affine2D().rotate_deg_around(origin_x, origin_y, angle_deg).transform((x, y))


def _line_fontpt(font_sizes, start, end, fontpt):
    sizes = [fs * 1.36 for fs in font_sizes[start:end] if fs]
    return max(sizes, default=fontpt)


def _paragraph_spacing(paragraph: dict | None) -> float:
    spacing = (paragraph or {}).get("line_spacing")
    if isinstance(spacing, (int, float)) and spacing == spacing and spacing > 0:
        return spacing / 1.35
    return 1.0


def _line_advance(line_h, paragraph, line_fontpt, fontpt):
    sized = line_h * max(line_fontpt / fontpt, 1.0)
    return max(sized * _paragraph_spacing(paragraph), line_fontpt * 2.25)


def _blank_advance(blank_h, paragraph):
    return blank_h * _paragraph_spacing(paragraph)


def _typed_note_advance(raw_font_size: float, paragraph: dict | None) -> float:
    """Samsung document-body line-box advance, grounded by vector PDF GT."""
    spacing = (paragraph or {}).get("line_spacing")
    if not isinstance(spacing, (int, float)) or spacing != spacing or spacing <= 0:
        spacing = TYPED_TEXT_DEFAULT_LINE_SPACING
    advance = raw_font_size * TYPED_TEXT_FONT_TO_PAGE * spacing
    if _is_todo(paragraph):
        advance = max(advance, TYPED_TEXT_TODO_MIN_H)
    return advance


def _is_todo(paragraph: dict | None) -> bool:
    item = (paragraph or {}).get("list")
    return bool(item and item.get("type") == "todo")


def _draw_text_segment(
    ax,
    renderer,
    inv,
    x,
    y,
    seg,
    fontpt,
    style,
    default_ink,
    angle_deg=0.0,
    origin=None,
    width_scale=1.0,
):
    b, it, u, st, c, hl, fs = style
    seg_fontpt = _style_fontpt(style, fontpt)
    hexc = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" if c else default_ink
    corners = _measure_text(
        ax, renderer, inv, x, y, seg, seg_fontpt, b, it, width_scale=width_scale
    )
    w = corners[:, 0].max() - corners[:, 0].min()
    y_top = corners[:, 1].min()
    y_bottom = corners[:, 1].max()
    line_transform = None
    text_x, text_y = x, y
    if angle_deg:
        origin_x, origin_y = origin or (x, y)
        text_x, text_y = _rotate_point(x, y, origin_x, origin_y, angle_deg)
        line_transform = mtransforms.Affine2D().rotate_deg_around(origin_x, origin_y, angle_deg) + ax.transData
    if hl:
        hexhl = f"#{hl[0]:02x}{hl[1]:02x}{hl[2]:02x}"
        fill_kw = {"transform": line_transform} if line_transform is not None else {}
        ax.fill_between([x, x + w], y_top, y_bottom, color=hexhl, zorder=2, linewidth=0, **fill_kw)
    text = ax.text(
        text_x, text_y, seg, color=hexc, fontsize=seg_fontpt, va="top", ha="left", zorder=3,
        fontweight="bold" if b else "normal", fontstyle="italic" if it else "normal",
        rotation=-angle_deg if angle_deg else 0.0, rotation_mode="anchor",
    )
    if width_scale != 1.0 and not angle_deg:
        text.set_transform(
            mtransforms.Affine2D()
            .translate(-text_x, -text_y)
            .scale(width_scale, 1.0)
            .translate(text_x, text_y)
            + ax.transData
        )
    text.set_in_layout(False)
    if u:
        line_kw = {"transform": line_transform} if line_transform is not None else {}
        ax.plot([x, x + w], [y_bottom, y_bottom], "-", color=hexc, lw=1.3, zorder=3, **line_kw)
    if st:
        y_mid = (y_top + y_bottom) / 2
        line_kw = {"transform": line_transform} if line_transform is not None else {}
        ax.plot([x, x + w], [y_mid, y_mid], "-", color=hexc, lw=1.3, zorder=3, **line_kw)
    return w


def _fit_segment_prefix(
    ax, renderer, inv, x, y, seg, fontpt, bold, italic, max_x, angle_deg=0.0,
    width_scale=1.0,
):
    lo, hi = 1, len(seg)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        corners = _measure_text(
            ax, renderer, inv, x, y, seg[:mid], fontpt, bold, italic,
            width_scale=width_scale,
        )
        width = corners[:, 0].max() - corners[:, 0].min()
        if x + width <= max_x:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _wrap_cut(seg: str, fit_len: int) -> tuple[str, str]:
    if fit_len >= len(seg):
        return seg, ""
    cut = fit_len
    ws = max(seg.rfind(" ", 0, fit_len + 1), seg.rfind("\t", 0, fit_len + 1))
    if ws > 0:
        cut = ws + 1
    head = seg[:cut]
    tail = seg[cut:].lstrip(" \t")
    if not head and seg:
        head, tail = seg[:1], seg[1:]
    return head, tail


def _wrap_plain_text(ax, renderer, inv, text, fontpt, max_width):
    wrapped_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            wrapped_lines.append("")
            continue
        remaining = line
        while remaining:
            corners = _measure_text(ax, renderer, inv, 0, 0, remaining, fontpt, False, False)
            width = corners[:, 0].max() - corners[:, 0].min()
            if width <= max_width:
                wrapped_lines.append(remaining)
                break
            fit_len = _fit_segment_prefix(ax, renderer, inv, 0, 0, remaining, fontpt, False, False, max_width)
            if fit_len <= 0:
                fit_len = 1
            head, tail = _wrap_cut(remaining, fit_len)
            wrapped_lines.append(head.rstrip())
            remaining = tail
    return "\n".join(wrapped_lines)


def _paragraph_prefix(paragraph: dict | None) -> str:
    if not paragraph or not paragraph.get("list"):
        return ""
    item = paragraph["list"]
    if item["type"] == "numbered":
        return f"{item.get('number', 1)}. "
    if item["type"] == "bullet":
        return "• "
    if item["type"] == "todo":
        return "☑ " if item.get("checked") else "☐ "
    return ""


def _is_checked_todo(paragraph: dict | None) -> bool:
    item = (paragraph or {}).get("list")
    return bool(item and item["type"] == "todo" and item.get("checked"))


def _render_rich_text(
    ax,
    parsed,
    *,
    x0,
    y0,
    max_width,
    line_h,
    blank_h,
    fontpt,
    default_ink,
    angle_deg=0.0,
    line_dir=1.0,
    sink=None,
    typed_note_model=False,
):
    """Shared rich-text renderer for note.note typed text and in-page text boxes.

    Layout is computed in an unrotated logical space (`x` = inline advance, `y` = next wrapped
    line) and only the final artists are rotated. This keeps wrapping/measurement identical across
    note.note text and text-box text, and is also why vertical boxes need an explicit anchor/line
    direction policy in `_text_box_layout` instead of relying on matplotlib's default text bbox.

    When `sink` is a list, segments are measured and recorded as `(x, y, seg, style, line_h)`
    tuples instead of drawn — this is the layout pass used to paginate note.note typed text across
    real .page files (see `_paginate_segments`). With `sink=None` it draws directly (text boxes).
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    bold, italic, underline, strike, color, highlight, font_size = _char_styles(parsed)
    paragraphs = parsed.get("paragraphs") or []
    default_raw_font_size = float(parsed.get("font_size") or 11.0)
    width_scale = TYPED_TEXT_GLYPH_WIDTH_SCALE if typed_note_model else 1.0

    def emit(x, y, seg, style, line_h_cur):
        if sink is None:
            return _draw_text_segment(
                ax, renderer, inv, x, y, seg, fontpt, style, default_ink,
                angle_deg=angle_deg, origin=(x0, y0), width_scale=width_scale,
            )
        corners = _measure_text(
            ax, renderer, inv, x, y, seg, _style_fontpt(style, fontpt), style[0], style[1],
            width_scale=width_scale,
        )
        sink.append((x, y, seg, style, line_h_cur))
        return corners[:, 0].max() - corners[:, 0].min()

    gi = 0
    y = y0
    for para_idx, line in enumerate(parsed["text"].split("\n")):
        paragraph = paragraphs[para_idx] if para_idx < len(paragraphs) else None
        line_start = gi
        line_end = gi + len(line)
        # Styled paragraphs (body1/heading*) carry decoded space-before/after; add space-before
        # ahead of the line and space-after once it's laid out, so headings breathe like the GT.
        space_before = ((paragraph or {}).get("space_before") or 0.0) * PARA_SPACE_UNIT
        space_after = ((paragraph or {}).get("space_after") or 0.0) * PARA_SPACE_UNIT
        y += space_before * line_dir
        raw_sizes = [fs for fs in font_size[line_start:line_end] if fs]
        raw_line_font_size = max(raw_sizes, default=default_raw_font_size)
        rendered_line_h = (
            _typed_note_advance(raw_line_font_size, paragraph)
            if typed_note_model
            else _line_advance(
                line_h,
                paragraph,
                _line_fontpt(font_size, line_start, line_end, fontpt),
                fontpt,
            )
        )
        indent = (paragraph or {}).get("indent") or 0
        line_x0 = x0 + indent * 70
        line_max_width = max(max_width - indent * 70, fontpt * 4)
        prefix = _paragraph_prefix(paragraph)
        checked_todo = _is_checked_todo(paragraph)
        if prefix:
            # Draw the list marker at the paragraph's own font size, not the base size, so the
            # number/bullet matches its list text instead of towering over smaller (e.g. 11pt) runs.
            para_font_raw = next((font_size[k] for k in range(line_start, line_end) if font_size[k]), None)
            prefix_pt = para_font_raw * 1.36 if para_font_raw else fontpt
            # Document-body lists use Samsung's measured hanging columns; text boxes retain the
            # older glyph-measured fallback because their bbox-local scale is independent.
            if typed_note_model:
                item_type = ((paragraph or {}).get("list") or {}).get("type")
                size_scale = (para_font_raw or default_raw_font_size) / 11.0
                if item_type == "numbered":
                    marker_indent = 0.0
                    prefix_w = TYPED_TEXT_NUMBER_BODY_INDENT * size_scale
                else:
                    marker_indent = (
                        TYPED_TEXT_TODO_MARKER_INDENT
                        if item_type == "todo"
                        else TYPED_TEXT_BULLET_MARKER_INDENT
                    ) * size_scale
                    prefix_w = TYPED_TEXT_LIST_BODY_INDENT * size_scale
            else:
                prefix_corners = _measure_text(
                    ax, renderer, inv, line_x0, y, prefix, prefix_pt, False, False
                )
                prefix_text_w = prefix_corners[:, 0].max() - prefix_corners[:, 0].min()
                prefix_w = max(prefix_text_w + prefix_pt * 0.9, prefix_pt * 2.4)
                marker_indent = 0.0
            prefix_color = TODO_DONE_COLOR if checked_todo else None
            emit(
                line_x0 + marker_indent,
                y,
                prefix,
                (False, False, False, False, prefix_color, None, para_font_raw),
                rendered_line_h,
            )
            line_x0 += prefix_w
            line_max_width = max(line_max_width - prefix_w, fontpt * 4)
        align = (paragraph or {}).get("alignment", "left")
        if line and align in {"center", "right"}:
            corners = _measure_text(
                ax, renderer, inv, line_x0, y, line, fontpt, False, False,
                angle_deg=angle_deg, width_scale=width_scale,
            )
            line_width = corners[:, 0].max() - corners[:, 0].min()
            if line_width < line_max_width:
                if align == "center":
                    line_x0 += (line_max_width - line_width) / 2
                else:
                    line_x0 += line_max_width - line_width
        max_x = line_x0 + line_max_width
        if not line:
            if typed_note_model:
                # The newline itself carries the active font of an empty paragraph. This is what
                # makes the controlled 11/14/19pt blank rows match their preceding blocks.
                blank_raw = (
                    font_size[line_start]
                    if line_start < len(font_size) and font_size[line_start]
                    else default_raw_font_size
                )
                blank_advance = _typed_note_advance(blank_raw, paragraph)
            else:
                blank_advance = _blank_advance(blank_h, paragraph)
            gi += 1
            y += (blank_advance + space_after) * line_dir
            continue
        x = line_x0
        i = 0
        while i < len(line):
            style = (
                bold[gi + i], italic[gi + i], underline[gi + i], strike[gi + i],
                color[gi + i], highlight[gi + i], font_size[gi + i],
            )
            if checked_todo:
                style = (
                    style[0],
                    style[1],
                    style[2],
                    True,
                    style[4] or TODO_DONE_COLOR,
                    style[5],
                    style[6],
                )
            j = i
            while j < len(line):
                next_style = (
                    bold[gi + j], italic[gi + j], underline[gi + j], strike[gi + j],
                    color[gi + j], highlight[gi + j], font_size[gi + j],
                )
                if checked_todo:
                    next_style = (
                        next_style[0],
                        next_style[1],
                        next_style[2],
                        True,
                        next_style[4] or TODO_DONE_COLOR,
                        next_style[5],
                        next_style[6],
                    )
                if next_style != style:
                    break
                j += 1
            seg = line[i:j]
            while seg:
                seg_fontpt = _style_fontpt(style, fontpt)
                corners = _measure_text(
                    ax, renderer, inv, x, y, seg, seg_fontpt, style[0], style[1],
                    width_scale=width_scale,
                )
                width = corners[:, 0].max() - corners[:, 0].min()
                if x + width <= max_x:
                    x += emit(x, y, seg, style, rendered_line_h)
                    seg = ""
                    continue
                fit_len = _fit_segment_prefix(
                    ax, renderer, inv, x, y, seg, seg_fontpt, style[0], style[1], max_x,
                    angle_deg=angle_deg, width_scale=width_scale,
                )
                if fit_len <= 0:
                    x = line_x0
                    y += rendered_line_h * line_dir
                    continue
                # If a styled segment would only fit by splitting inside a word because the
                # current line is already partially occupied (e.g. "... testo in " + bold
                # "grassetto"), move the WHOLE segment to the next line and re-measure there.
                # This avoids artificial extra rows that come purely from run boundaries rather
                # than the paragraph's own word wrapping.
                if x > line_x0 and fit_len < len(seg) and not re.search(r"[ \t]", seg[:fit_len]):
                    seg_corners = _measure_text(
                        ax, renderer, inv, line_x0, y, seg, seg_fontpt, style[0], style[1],
                        width_scale=width_scale,
                    )
                    seg_width = seg_corners[:, 0].max() - seg_corners[:, 0].min()
                    if line_x0 + seg_width <= max_x:
                        x = line_x0
                        y += rendered_line_h * line_dir
                        continue
                head, seg = _wrap_cut(seg, fit_len)
                if not head:
                    x = line_x0
                    y += rendered_line_h * line_dir
                    continue
                x += emit(x, y, head, style, rendered_line_h)
                if seg:
                    x = line_x0
                    y += rendered_line_h * line_dir
            i = j
        gi += len(line) + 1
        y += (rendered_line_h + space_after) * line_dir
    return y


def render_typed_text(ax, parsed, bg_color, x0=TYPED_TEXT_X0, y0=TYPED_TEXT_Y0,
                      line_h=TYPED_TEXT_LINE_H, blank_h=TYPED_TEXT_BLANK_H, fontpt=TYPED_TEXT_FONTPT,
                      default_ink=DEFAULT_INK):
    """Draw all parsed typed text on one axes (no pagination). Returns the last baseline y.

    render_document uses the paginated path (paginate_typed_text/draw_typed_page) instead; this
    is kept for single-axes callers (e.g. notebooks) that want the whole flow in one place.
    """
    return _render_rich_text(
        ax, parsed, x0=x0, y0=y0, max_width=max(ax.get_xlim()) - x0,
        line_h=line_h, blank_h=blank_h, fontpt=fontpt, default_ink=default_ink,
        typed_note_model=True,
    )


def _paginate_segments(sink, y0, page_height):
    """Group recorded segments into visual lines and split them across page-height bands.

    Samsung paginates typed text by whole line boxes inside the decoded Common body's vertical
    margins. A break retains the inter-line gap immediately before the bumped line (notably a
    heading's space-before), while a uniform paragraph starts the next page with no extra gap.
    """
    lines: list[dict] = []
    by_y: dict[float, dict] = {}
    for x, y, seg, style, line_h in sink:
        key = round(y, 2)
        ln = by_y.get(key)
        if ln is None:
            ln = {"y": y, "advance": line_h, "segs": []}
            by_y[key] = ln
            lines.append(ln)
        ln["segs"].append((x, seg, style))
        ln["advance"] = max(ln["advance"], line_h)
    lines.sort(key=lambda ln: ln["y"])

    pages: list[list[dict]] = []
    current: list[dict] = []
    content_height = page_height - 2.0 * TYPED_TEXT_VERTICAL_MARGIN
    base = lines[0]["y"] if lines else y0
    previous = None
    for ln in lines:
        flow_y = ln["y"] - base
        if current and flow_y + ln["advance"] > content_height:
            pages.append(current)
            current = []
            lead_gap = max(0.0, ln["y"] - (previous["y"] + previous["advance"]))
            base = ln["y"] - lead_gap
            flow_y = lead_gap
        current.append({"y": y0 + flow_y, "segs": ln["segs"]})
        previous = ln
    if current:
        pages.append(current)
    return pages


def paginate_typed_text(parsed, width, height, figsize, default_ink=DEFAULT_INK):
    """Lay the typed text out once on a scratch page-sized axes and split it into page slots."""
    fig, ax = plt.subplots(figsize=figsize)
    try:
        ax.set_xlim(0, width)
        ax.set_ylim(height, 0)
        sink: list = []
        _render_rich_text(
            ax, parsed, x0=TYPED_TEXT_X0, y0=TYPED_TEXT_Y0, max_width=width - TYPED_TEXT_X0,
            line_h=TYPED_TEXT_LINE_H, blank_h=TYPED_TEXT_BLANK_H, fontpt=TYPED_TEXT_FONTPT,
            default_ink=default_ink, sink=sink, typed_note_model=True,
        )
    finally:
        plt.close(fig)
    return _paginate_segments(sink, TYPED_TEXT_Y0, height)


def draw_typed_page(ax, page_lines, fontpt=TYPED_TEXT_FONTPT, default_ink=DEFAULT_INK):
    """Draw one paginated slot (from paginate_typed_text) onto a page's axes."""
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    for ln in page_lines:
        for x, seg, style in ln["segs"]:
            _draw_text_segment(
                ax, renderer, inv, x, ln["y"], seg, fontpt, style, default_ink,
                width_scale=TYPED_TEXT_GLYPH_WIDTH_SCALE,
            )


# The header/"evidenzia" cell ink (foreground_color ff3a3a3d) — Samsung's
# highlighted rows/columns carry it AND get the theme fill behind them (there is
# no per-cell fill in that case). Plain bold cells keep the default ink ff252525.
_HEADER_INK = (0x3A, 0x3A, 0x3D)


def _argb_to_rgb(argb):
    return ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF)


def _table_border(block):
    """Reduce a 4-entry border block to `(has_v, has_h, color, radius)`.

    Entries 0/2 are the vertical edges/lines, 1/3 the horizontal (paired members
    never differ). A border is on when its ARGB is opaque and width > 0.
    """
    def on(entry):
        return entry["argb"] >> 24 != 0 and entry["width"] > 0

    has_v, has_h = on(block[0]), on(block[1])
    color = next((_argb_to_rgb(e["argb"]) for e in block if on(e)), None)
    radius = block[0]["radius_x"] if has_v else (block[1]["radius_x"] if has_h else 0.0)
    return {"has_v": has_v, "has_h": has_h, "color": color, "radius": radius}


def structural_table_render_model(table):
    """Project a byte-exact structural table (`note_doc_tables`) to render-ready form.

    Geometry comes from the page-local grid (`note_table_grid`). Per-cell character
    style comes from the frame spans (`table_cell_style`); the background fill is the
    explicit `fill_argb`, or the theme fill for header/"evidenzia" cells (fg ==
    ff3a3a3d). The outer frame + inner grid come from the decoded border blocks
    (`outer_borders` / `grid_borders`): colour, width, corner radius, and which
    edges are enabled. Host page is the wrap `table_index` (0-based page index).
    """
    x_edges, y_edges = note_table_grid(table)
    theme_fill = _argb_to_rgb(table["theme_fill_argb"])
    cells = []
    for r, row in enumerate(table["rows"]):
        for c in row["cells"]:
            style = table_cell_style(c)
            if c["fill_argb"] >> 24:
                fill = _argb_to_rgb(c["fill_argb"])
            elif style["color"] == _HEADER_INK:
                fill = theme_fill
            else:
                fill = None
            cells.append({
                "row": r, "col": c["col"],
                "text": c["frame"]["text"].rstrip("\n"),
                "fill": fill,
                **style,
            })
    return {
        "x_edges": x_edges, "y_edges": y_edges, "cells": cells,
        "outer": _table_border(table["outer_borders"]),
        "inner": _table_border(table["grid_borders"]),
        "page_index": table["table_index"], "bbox": table["bbox"],
    }


# ⚠ HEURISTIC: matplotlib point → page-unit factor for the 9×12in figure (the app
# uses the same 3.40); used to estimate a cell's text extent so under/strike lines
# span only the text, not the whole cell.
_TABLE_PT_TO_PAGE = 3.40


def render_table(ax, table, text_color=DEFAULT_INK, fontpt=15, pad=18):
    """Draw a structural table (`structural_table_render_model`) with its decoded style.

    Cell texts/geometry/fills/character style and the border blocks all come
    byte-exactly from the note.note type-22 object. `font_size` is the shrink-to-fit
    baseline (only shrunk if the text would overflow the cell), so a cell set larger
    (e.g. size 20) actually renders larger. Under/strike lines span the text only.
    """
    x_edges, y_edges = table["x_edges"], table["y_edges"]
    x0, x1, y0, y1 = x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]
    outer, inner = table["outer"], table["inner"]

    # Explicit / header background fills sit beneath the borders.
    for cell in table["cells"]:
        if not cell["fill"]:
            continue
        fx0, fx1 = x_edges[cell["col"]], x_edges[cell["col"] + 1]
        fy0, fy1 = y_edges[cell["row"]], y_edges[cell["row"] + 1]
        ax.add_patch(plt.Rectangle(
            (fx0, min(fy0, fy1)), fx1 - fx0, abs(fy1 - fy0),
            facecolor=color_hex(cell["fill"]), edgecolor="none", zorder=1))

    lw = 1.2
    fallback_rgb = (0x8A, 0x8F, 0x9A)
    outer_hex = color_hex(outer["color"] or fallback_rgb)
    inner_hex = color_hex(inner["color"] or outer["color"] or fallback_rgb)
    # A boundary edge (frame top/bottom/left/right) is drawn if EITHER the outer
    # frame OR the grid enables it — so "only horizontal grid, no frame" still
    # closes top+bottom. Interior lines are grid-only. A full, rounded frame draws
    # its own boundary (skip the straight boundary lines then).
    rounded = outer["has_v"] and outer["has_h"] and outer["radius"] > 0
    if rounded:
        r = outer["radius"]
        ax.add_patch(FancyBboxPatch(
            (x0, min(y0, y1)), x1 - x0, abs(y1 - y0),
            boxstyle=f"round,pad=0,rounding_size={r}",
            fill=False, edgecolor=outer_hex, lw=lw, zorder=2, mutation_aspect=1))
    boundary_h_hex = outer_hex if outer["has_h"] else inner_hex
    boundary_v_hex = outer_hex if outer["has_v"] else inner_hex
    if inner["has_h"]:  # interior horizontals
        for y in y_edges[1:-1]:
            ax.plot([x0, x1], [y, y], "-", color=inner_hex, lw=lw, zorder=2)
    if (outer["has_h"] or inner["has_h"]) and not rounded:  # top + bottom
        for y in (y0, y1):
            ax.plot([x0, x1], [y, y], "-", color=boundary_h_hex, lw=lw, zorder=2)
    if inner["has_v"]:  # interior verticals
        for x in x_edges[1:-1]:
            ax.plot([x, x], [y0, y1], "-", color=inner_hex, lw=lw, zorder=2)
    if (outer["has_v"] or inner["has_v"]) and not rounded:  # left + right
        for x in (x0, x1):
            ax.plot([x, x], [y0, y1], "-", color=boundary_v_hex, lw=lw, zorder=2)

    for cell in table["cells"]:
        cx0 = x_edges[cell["col"]]
        cx1 = x_edges[cell["col"] + 1]
        cx = cx0 + pad
        cy = (y_edges[cell["row"]] + y_edges[cell["row"] + 1]) / 2
        text = cell["text"]
        base_pt = cell.get("font_size") or fontpt
        usable = max(cx1 - cx0 - 2 * pad, 1.0)
        approx_width = max(len(text), 1) * base_pt * 7.0
        cell_fontpt = max(5.5, min(base_pt, base_pt * usable / approx_width))
        color = cell.get("color")
        hexc = color_hex(color) if color and color != TEXT_DEFAULT_COLOR else text_color
        ax.text(
            cx, cy, text, color=hexc, fontsize=cell_fontpt, va="center", ha="left", zorder=3,
            fontweight="bold" if cell.get("bold") else "normal",
            fontstyle="italic" if cell.get("italic") else "normal",
        )
        # Under/strike over the text extent only (estimated), not the whole cell.
        text_w = min(len(text) * cell_fontpt * 0.5 * _TABLE_PT_TO_PAGE, usable)
        if cell.get("underline"):
            uy = cy - cell_fontpt * 0.55
            ax.plot([cx, cx + text_w], [uy, uy], "-", color=hexc, lw=1.0, zorder=3)
        if cell.get("strikethrough"):
            ax.plot([cx, cx + text_w], [cy, cy], "-", color=hexc, lw=1.0, zorder=3)


def _resolve_bg(bg, stored_bg):
    """Map the `bg` argument to a hex color. None → the file's stored bg; a name via NAMED_BG."""
    if bg is None:
        return stored_bg
    return NAMED_BG.get(bg, bg)


def _typed_text_target_page(parsed) -> int | None:
    if not parsed:
        return None
    m = re.search(r"\bpagina\s+(\d+)\b", parsed["text"], flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def render_document(path, *, out=None, fmt="png", bg=None, page=None,
                    table_page=None, figsize=(9, 12), show=None):
    """Render every page of a .sdocx to one matplotlib Figure per page.

    This is the whole rendering pipeline that used to live in notebooks/03_ink.ipynb: it lists
    the pages in true document order, parses each, loads imported images + freehand drawings, and
    composes strokes/shapes/images (plus the note-level typed text and table) onto a page-sized
    figure. Returns the list of Figures.

    Parameters
    ----------
    path : str | Path
        The .sdocx container.
    out : str | Path | None
        If given, save one image per page (`<stem>-page-NN.<fmt>`) into this directory and close
        each figure. If None, the figures are shown (see `show`) and returned open.
    fmt : str
        Output image format when saving ("png", "svg", ...).
    bg : str | None
        Page background: None uses the color stored in the file (dark `#252525`, as the notebook
        did); "dark"/"white" force those; any other value is treated as an explicit hex color.
        On a light background the default ink flips to black so nothing renders invisible.
    page : int | None
        1-based page index to render just one page; None renders all pages.
    table_page : int | None
        1-based page index on which to draw the note's table(s). None uses a small heuristic:
        if the typed text names a target page (e.g. "pagina 3"), draw the table on the previous
        page; otherwise fall back to page 4, which matches the benchmark sample.
    figsize : tuple
        Per-page figure size in inches.
    show : bool | None
        Whether to `plt.show()` each figure. None → True when `out` is None (notebook use),
        else False.
    """
    path = Path(path)
    if show is None:
        show = out is None
    out_dir = Path(out) if out is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    all_pages = list_pages(path)

    # Typed ("keyboard") text and tables are stored once per document in note.note, NOT per page,
    # and note.note carries no page reference — so their page is a heuristic: typed text goes on
    # the first otherwise-empty page, and the table on `table_page`. Both are where Samsung Notes
    # displays them.
    note = load_note(path) or b""
    typed_text = parse_typed_text(note)
    typed_text_placed = False
    typed_pages = None  # paginated typed-text slots, computed lazily on the anchor page
    typed_anchor_idx = None
    # Tables are decoded byte-exactly (the type-22 object) and each carries its own
    # host-page index (`page_index`), so — unlike typed text — no placement guess is
    # needed. `table_page` (1-based) still forces all tables onto one page if given.
    tables = [structural_table_render_model(t) for t in note_doc_tables(note, parse_note_doc(note))] if note else []
    typed_text_target = _typed_text_target_page(typed_text)
    raster_indices = raster_media_indices(path)

    figures = []
    for idx, page_name in enumerate(all_pages, start=1):
        if page is not None and idx != page:
            continue

        _, page_bytes, note_bg = load_page_with_bg(path, page_name)
        # The authoritative paper color is a per-.page field (RE 2026-07-09), not note.note —
        # note_bg is empty on the whole corpus. Fall back to the note-level bg, then white.
        page_paper = page_background_color(page_bytes)
        stored_bg = ("#%02x%02x%02x" % page_paper) if page_paper else note_bg
        page_bg = _resolve_bg(bg, stored_bg)
        default_ink = _contrast_ink(page_bg)
        page_result = parse_page(page_bytes)
        kept, total = page_result["kept"], page_result["stroke_count"]
        shapes = page_result["shapes"]
        text_boxes = page_result["text_boxes"]
        sticky_notes = page_result["sticky_notes"]

        # Imported images and freehand drawings render the same way. Both are now read from the
        # page object tree, then resolved to media bytes here.
        placements = list(page_result["images"]) + [
            d for d in page_result["drawings"] if d["media_index"] in raster_indices
        ]
        images = []
        for pl in placements:
            media = load_media_by_index(path, pl["media_index"])
            if media is not None:
                images.append({"bbox": pl["bbox"], "data": media[1], "angle_deg": pl.get("angle_deg", 0.0)})

        # Embedded PDF/custom-image template: resolve the referenced media and composite it as the
        # full-page background. Custom images are matched by the basename stored in template_uri.
        template_image = None
        tmpl = page_result["template"]
        if tmpl is not None and tmpl.get("kind") == "pdf":
            media = load_media_by_index(path, tmpl["pdf_media_index"])
            if media is not None:
                template_image = rasterize_pdf_page(media[1], tmpl["pdf_page_index"], page_result["width"])
        elif tmpl is not None and tmpl.get("kind") == "image":
            wanted = tmpl["name"]
            with zipfile.ZipFile(path) as z:
                match = next((n for n in z.namelist() if n.startswith("media/") and n.rsplit("@", 1)[-1] == wanted), None)
                if match is not None:
                    template_image = np.asarray(Image.open(io.BytesIO(z.read(match))).convert("RGBA"))

        # Each table declares its own 0-based host page; `table_page` (1-based) forces all.
        page_tables = [
            t for t in tables
            if (idx == table_page if table_page is not None else t["page_index"] == idx - 1)
        ]
        is_empty = (
            kept == 0 and not shapes and not images and not text_boxes
            and not sticky_notes and not page_tables
        )
        shows_typed_text = (
            typed_text is not None
            and not typed_text_placed
            and ((typed_text_target is not None and idx == typed_text_target) or (typed_text_target is None and is_empty))
        )

        mismatch = "  ⚠ MISMATCH" if kept != total else ""
        extras = "".join(
            part for part in (
                f"  +{len(shapes)} shapes" if shapes else "",
                f"  +{len(images)} images" if images else "",
                f"  +{len(text_boxes)} text boxes" if text_boxes else "",
                f"  +{len(sticky_notes)} sticky notes" if sticky_notes else "",
                f"  +{len(page_tables)} tables" if page_tables else "",
                "  +typed text" if shows_typed_text else "",
            )
        )
        title = (
            f"page {idx}/{len(all_pages)}  ·  {page_name[:8]}  ·  "
            f"{kept}/{total} strokes{extras}{mismatch}  ·  bg {page_bg}"
        )

        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor(page_bg)
        # Always render through render_page so the grid template shows even on empty pages.
        render_page(
            ax, page_result["strokes"], page_bg, title=title, shapes=shapes, images=images,
            text_boxes=text_boxes, sticky_notes=sticky_notes,
            page_size=(page_result["width"], page_result["height"]), template=page_result["template"],
            default_ink=default_ink, template_image=template_image,
        )
        for table in page_tables:
            render_table(ax, table, text_color=default_ink)
        if shows_typed_text:
            # note.note typed text is a document-level flow: lay it out once, then paginate it
            # across this page and the following .page files by page height (whole lines bumped to
            # the next page, matching Samsung), instead of stretching one page to hold all of it.
            typed_pages = paginate_typed_text(
                typed_text, page_result["width"], page_result["height"], figsize, default_ink=default_ink
            )
            typed_anchor_idx = idx
            typed_text_placed = True
        if typed_pages is not None and typed_anchor_idx is not None:
            slot = idx - typed_anchor_idx
            if 0 <= slot < len(typed_pages):
                draw_typed_page(ax, typed_pages[slot], default_ink=default_ink)
        fig.tight_layout()

        if out_dir is not None:
            dest = out_dir / f"{path.stem}-page-{idx:02d}.{fmt}"
            fig.savefig(dest, facecolor=fig.get_facecolor())
        if show:
            plt.show()
        elif out_dir is not None:
            plt.close(fig)
        figures.append(fig)

    return figures
