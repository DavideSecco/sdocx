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
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import Ellipse, FancyBboxPatch
from PIL import Image

from pysdocx.container import (
    list_pages,
    load_media_by_index,
    load_note,
    load_page_with_bg,
    raster_media_indices,
)
from pysdocx.ink import color_hex
from pysdocx.note import parse_tables, parse_typed_text
from pysdocx.page import GRID_ORIGIN, GRID_SPACING, parse_page

MAX_PRESSURE = 1400.0
DEFAULT_INK = "#ffffff"
GRID_COLOR = "#d3dae8"  # faint blue-gray, as in the Samsung Notes squared template
TEXT_DEFAULT_COLOR = (37, 37, 37)  # body default; ≈ the dark page bg, so we contrast it below
TODO_DONE_COLOR = (150, 150, 150)
TABLE_LINE_COLOR = "#8a8f9a"

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


def draw_grid(ax, width, height, spacing=GRID_SPACING, origin=GRID_ORIGIN, color=GRID_COLOR, lw=0.6):
    """Draw the squared-paper template: light vertical + horizontal lines every `spacing`
    page units, spanning the whole page (0..width, 0..height). `origin` is the page-coord
    position of a grid line on each axis (the template has a ~44px top margin, so vertical
    lines start at x=0 but horizontal ones start ~44px down) — measured from the GT photos."""
    xs = np.arange(origin[0] % spacing, width + 0.5, spacing)
    ys = np.arange(origin[1] % spacing, height + 0.5, spacing)
    segments = [((x, 0.0), (x, height)) for x in xs] + [((0.0, y), (width, y)) for y in ys]
    ax.add_collection(LineCollection(segments, colors=color, linewidths=lw, zorder=0.5))


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
    else:  # polygons + heart + cross + freeform (smooth already flattened): draw the real outline
        poly = list(pts) + ([pts[0]] if closed else [])
        ax.plot([q[0] for q in poly], [q[1] for q in poly], "-", color=color, linewidth=lw, zorder=2)


def _text_box_layout(box):
    """Anchor/wrap parameters for a text-box from its bbox + decoded rotation.

    Samsung stores the text-box angle as the same clockwise-positive f32 used by images, but the
    TEXT anchor itself is not always the bbox's top-left corner after rotation. Near-vertical
    boxes (≈90°/270°) visually start from the bbox's top-RIGHT/left edge respectively; anchoring
    every box at `(x0, y0)` mirrors the column order compared to the GT sample. This helper picks
    a stable anchor corner and logical wrap width before the shared rich-text renderer takes over.
    """
    x0, y0, x1, y1 = box["bbox"]
    angle_deg = (box.get("angle_deg") or 0.0) % 360.0
    box_w = max(x1 - x0 - 16, 1.0)
    box_h = max(y1 - y0 - 16, 1.0)
    if abs(angle_deg - 90.0) <= 15.0:
        return {
            "anchor_x": x1 - 8,
            "anchor_y": y0 + 8,
            "wrap_width": box_h,
            "line_dir": 1.0,
        }
    if abs(angle_deg - 270.0) <= 15.0:
        return {
            "anchor_x": x0 + 8,
            "anchor_y": y1 - 8,
            "wrap_width": box_h,
            "line_dir": 1.0,
        }
    return {
        "anchor_x": x0 + 8,
        "anchor_y": y0 + 8,
        "wrap_width": box_w,
        "line_dir": 1.0,
    }


def render_page(ax, strokes, bg_color, title=None, shapes=(), images=(), text_boxes=(),
                sticky_notes=(), page_size=None, template=None, default_ink=DEFAULT_INK):
    """Draw a parsed page (strokes, inserted shapes, imported images) onto a matplotlib Axes.

    `images` is a list of {"bbox": (x0, y0, x1, y1), "data": <image bytes>}. When `page_size`
    (width, height) is given, the axes are fixed to the whole page (not autoscaled to content)
    and, if `template` is a grid template, the squared background is drawn under everything.
    `default_ink` is the fallback color for strokes/shapes whose stored color matches the
    background (contrast against the page); it is white on a dark page, black on a light one.
    """
    ax.set_facecolor(bg_color)
    if page_size is not None:
        ax.set_xlim(0, page_size[0])
        ax.set_ylim(page_size[1], 0)  # y increases downward in page coords

    # Squared-paper background goes above the flat fill but below images/strokes.
    if page_size is not None and template is not None and template["kind"] == "grid":
        draw_grid(ax, page_size[0], page_size[1])

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


def _measure_text(ax, renderer, inv, x, y, text, fontpt, bold, italic, angle_deg=0.0):
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
):
    b, it, u, st, c, hl, fs = style
    seg_fontpt = _style_fontpt(style, fontpt)
    hexc = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" if c else default_ink
    corners = _measure_text(ax, renderer, inv, x, y, seg, seg_fontpt, b, it)
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
    text.set_in_layout(False)
    if u:
        line_kw = {"transform": line_transform} if line_transform is not None else {}
        ax.plot([x, x + w], [y_bottom, y_bottom], "-", color=hexc, lw=1.3, zorder=3, **line_kw)
    if st:
        y_mid = (y_top + y_bottom) / 2
        line_kw = {"transform": line_transform} if line_transform is not None else {}
        ax.plot([x, x + w], [y_mid, y_mid], "-", color=hexc, lw=1.3, zorder=3, **line_kw)
    return w


def _fit_segment_prefix(ax, renderer, inv, x, y, seg, fontpt, bold, italic, max_x, angle_deg=0.0):
    lo, hi = 1, len(seg)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        corners = _measure_text(ax, renderer, inv, x, y, seg[:mid], fontpt, bold, italic)
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
):
    """Shared rich-text renderer for note.note typed text and in-page text boxes.

    Layout is computed in an unrotated logical space (`x` = inline advance, `y` = next wrapped
    line) and only the final artists are rotated. This keeps wrapping/measurement identical across
    note.note text and text-box text, and is also why vertical boxes need an explicit anchor/line
    direction policy in `_text_box_layout` instead of relying on matplotlib's default text bbox.
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    bold, italic, underline, strike, color, highlight, font_size = _char_styles(parsed)
    paragraphs = parsed.get("paragraphs") or []

    gi = 0
    y = y0
    for para_idx, line in enumerate(parsed["text"].split("\n")):
        paragraph = paragraphs[para_idx] if para_idx < len(paragraphs) else None
        line_start = gi
        line_end = gi + len(line)
        rendered_line_h = _line_advance(line_h, paragraph, _line_fontpt(font_size, line_start, line_end, fontpt), fontpt)
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
            # Reserve a column sized to the marker's actual glyph width plus a font-proportional
            # gap, so the text starts clear of the marker regardless of glyph (single digit vs
            # bullet vs checkbox) instead of butting right against it.
            prefix_corners = _measure_text(ax, renderer, inv, line_x0, y, prefix, prefix_pt, False, False)
            prefix_text_w = prefix_corners[:, 0].max() - prefix_corners[:, 0].min()
            prefix_w = max(prefix_text_w + prefix_pt * 0.9, prefix_pt * 2.4)
            prefix_color = TODO_DONE_COLOR if checked_todo else None
            _draw_text_segment(
                ax,
                renderer,
                inv,
                line_x0,
                y,
                prefix,
                fontpt,
                (False, False, False, False, prefix_color, None, para_font_raw),
                default_ink,
                angle_deg=angle_deg,
                origin=(x0, y0),
            )
            line_x0 += prefix_w
            line_max_width = max(line_max_width - prefix_w, fontpt * 4)
        align = (paragraph or {}).get("alignment", "left")
        if line and align in {"center", "right"}:
            corners = _measure_text(ax, renderer, inv, line_x0, y, line, fontpt, False, False, angle_deg=angle_deg)
            line_width = corners[:, 0].max() - corners[:, 0].min()
            if line_width < line_max_width:
                if align == "center":
                    line_x0 += (line_max_width - line_width) / 2
                else:
                    line_x0 += line_max_width - line_width
        max_x = line_x0 + line_max_width
        if not line:
            gi += 1
            y += _blank_advance(blank_h, paragraph) * line_dir
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
                    ax, renderer, inv, x, y, seg, seg_fontpt, style[0], style[1]
                )
                width = corners[:, 0].max() - corners[:, 0].min()
                if x + width <= max_x:
                    x += _draw_text_segment(
                        ax,
                        renderer,
                        inv,
                        x,
                        y,
                        seg,
                        fontpt,
                        style,
                        default_ink,
                        angle_deg=angle_deg,
                        origin=(x0, y0),
                    )
                    seg = ""
                    continue
                fit_len = _fit_segment_prefix(
                    ax, renderer, inv, x, y, seg, seg_fontpt, style[0], style[1], max_x, angle_deg=angle_deg
                )
                if fit_len <= 0:
                    x = line_x0
                    y += rendered_line_h * line_dir
                    continue
                head, seg = _wrap_cut(seg, fit_len)
                if not head:
                    x = line_x0
                    y += rendered_line_h * line_dir
                    continue
                x += _draw_text_segment(
                    ax,
                    renderer,
                    inv,
                    x,
                    y,
                    head,
                    fontpt,
                    style,
                    default_ink,
                    angle_deg=angle_deg,
                    origin=(x0, y0),
                )
                if seg:
                    x = line_x0
                    y += rendered_line_h * line_dir
            i = j
        gi += len(line) + 1
        y += rendered_line_h * line_dir
    return y


def render_typed_text(ax, parsed, bg_color, x0=64, y0=80, line_h=66, blank_h=48, fontpt=17,
                      default_ink=DEFAULT_INK):
    """Draw parsed typed text with inline rich-text runs, wrapped to the page width.

    Returns the y of the last baseline drawn, so the caller can grow the page to contain text
    that runs past the nominal page height (Samsung stores this as one tall scrolling page).
    """
    return _render_rich_text(
        ax,
        parsed,
        x0=x0,
        y0=y0,
        max_width=max(ax.get_xlim()) - x0,
        line_h=line_h,
        blank_h=blank_h,
        fontpt=fontpt,
        default_ink=default_ink,
    )


def render_table(ax, table, line_color=TABLE_LINE_COLOR, text_color=DEFAULT_INK, fontpt=15, pad=18):
    """Draw a table (from pysdocx.parse_tables) as a grid of cells with their text.

    The table's cell texts + geometry live in note.note (like the typed text); parse_tables
    reconstructs the row/column grid from the cell anchor points. Each cell also carries its own
    rich-text style (`bold`/`italic`/`underline`/`color`/`font_size`, from note.py's `_cell_style`
    — the same per-run TLV markers as the document's typed text, just scoped to the cell's own
    text instead of the document-wide field). `font_size` becomes the shrink-to-fit baseline
    (still capped by `fontpt`/the cell width) instead of a flat size for every cell, so a cell
    explicitly set smaller (e.g. Samsung Notes' own auto-shrink) renders smaller than its
    neighbors, not just when its width forces it to.
    """
    x_edges, y_edges = table["x_edges"], table["y_edges"]
    for x in x_edges:
        ax.plot([x, x], [y_edges[0], y_edges[-1]], "-", color=line_color, lw=1.2, zorder=2)
    for y in y_edges:
        ax.plot([x_edges[0], x_edges[-1]], [y, y], "-", color=line_color, lw=1.2, zorder=2)
    for cell in table["cells"]:
        x0 = x_edges[cell["col"]]
        x1 = x_edges[cell["col"] + 1]
        cx = x0 + pad
        cy = (y_edges[cell["row"]] + y_edges[cell["row"] + 1]) / 2
        text = cell["text"]
        base_pt = min(cell.get("font_size") or fontpt, fontpt)
        usable = max(x1 - x0 - 2 * pad, 1.0)
        approx_width = max(len(text), 1) * base_pt * 7.0
        cell_fontpt = max(5.5, min(base_pt, base_pt * usable / approx_width))
        color = cell.get("color")
        hexc = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}" if color and color != TEXT_DEFAULT_COLOR else text_color
        ax.text(
            cx, cy, text, color=hexc, fontsize=cell_fontpt, va="center", ha="left", zorder=3,
            fontweight="bold" if cell.get("bold") else "normal",
            fontstyle="italic" if cell.get("italic") else "normal",
        )
        if cell.get("underline"):
            ax.plot([cx, x1 - pad], [cy - cell_fontpt * 0.55, cy - cell_fontpt * 0.55], "-", color=hexc, lw=1.0, zorder=3)


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
    tables = parse_tables(note)
    typed_text_target = _typed_text_target_page(typed_text)
    table_target_page = table_page
    if table_target_page is None and tables:
        table_target_page = typed_text_target - 1 if typed_text_target and typed_text_target > 1 else 4
    raster_indices = raster_media_indices(path)

    figures = []
    for idx, page_name in enumerate(all_pages, start=1):
        if page is not None and idx != page:
            continue

        _, page_bytes, stored_bg = load_page_with_bg(path, page_name)
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

        page_tables = [t for t in tables if t["bbox"] is not None] if idx == table_target_page else []
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
            default_ink=default_ink,
        )
        for table in page_tables:
            render_table(ax, table, text_color=default_ink)
        if shows_typed_text:
            bottom = render_typed_text(ax, typed_text, page_bg, default_ink=default_ink)
            typed_text_placed = True
            # note.note typed text is one tall scrolling page and can run past the nominal page
            # height; grow the axes (and the figure, so the text isn't squished) to contain it
            # instead of letting the tail bleed past the axes onto the tick labels.
            page_height = page_result["height"]
            if bottom is not None and bottom + 80 > page_height:
                new_height = bottom + 80
                ax.set_ylim(new_height, 0)
                fig.set_size_inches(figsize[0], figsize[1] * new_height / page_height)
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
