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

    # Squared-paper background goes above the flat fill but below images/strokes.
    if page_size is not None and template is not None and template["kind"] == "grid":
        draw_grid(ax, page_size[0], page_size[1])

    # Imported images go underneath everything else. The axis is y-inverted at
    # the end (page coords have y increasing downward), so use origin="lower"
    # with the natural extent to keep the picture itself upright.
    for im in images:
        x0, y0, x1, y1 = im["bbox"]
        pic = np.asarray(Image.open(io.BytesIO(im["data"])).convert("RGB"))
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
        x0, y0, _x1, _y1 = box["bbox"]
        ax.text(
            x0 + 8, y0 + 8, box["text"], color=default_ink, fontsize=15,
            va="top", ha="left", zorder=3, wrap=True,
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
    """Expand per-run styles into per-character (bold, italic, underline, strike, color, highlight)
    arrays."""
    n = len(parsed["text"])
    bold = [False] * n
    italic = [False] * n
    underline = [False] * n
    strike = [False] * n
    color = [None] * n
    highlight = [None] * n
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
    return bold, italic, underline, strike, color, highlight


def render_typed_text(ax, parsed, bg_color, x0=64, y0=80, line_h=60, blank_h=34, fontpt=17,
                      default_ink=DEFAULT_INK):
    """Draw parsed typed text onto the axes with inline bold/italic/underline/strikethrough,
    color and highlight background.

    The default text color equals the dark page background, so it falls back to the contrast ink
    (same idea as the stroke renderer); explicit colors (e.g. red "testorosso") are kept.
    """
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    bold, italic, underline, strike, color, highlight = _char_styles(parsed)

    gi = 0
    y = y0
    for line in parsed["text"].split("\n"):
        if not line:
            gi += 1
            y += blank_h
            continue
        x = x0
        i = 0
        while i < len(line):
            style = (
                bold[gi + i], italic[gi + i], underline[gi + i], strike[gi + i],
                color[gi + i], highlight[gi + i],
            )
            j = i
            while j < len(line) and (
                bold[gi + j], italic[gi + j], underline[gi + j], strike[gi + j],
                color[gi + j], highlight[gi + j],
            ) == style:
                j += 1
            seg = line[i:j]
            b, it, u, st, c, hl = style
            hexc = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" if c else default_ink
            t = ax.text(
                x, y, seg, color=hexc, fontsize=fontpt, va="top", ha="left", zorder=3,
                fontweight="bold" if b else "normal", fontstyle="italic" if it else "normal",
            )
            corners = inv.transform(t.get_window_extent(renderer).corners())
            w = corners[:, 0].max() - corners[:, 0].min()
            y_top = corners[:, 1].min()
            y_bottom = corners[:, 1].max()
            if hl:
                hexhl = f"#{hl[0]:02x}{hl[1]:02x}{hl[2]:02x}"
                ax.fill_between([x, x + w], y_top, y_bottom, color=hexhl, zorder=2, linewidth=0)
            if u:
                ax.plot([x, x + w], [y_bottom, y_bottom], "-", color=hexc, lw=1.3, zorder=3)
            if st:
                y_mid = (y_top + y_bottom) / 2
                ax.plot([x, x + w], [y_mid, y_mid], "-", color=hexc, lw=1.3, zorder=3)
            x += w
            i = j
        gi += len(line) + 1
        y += line_h


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
            render_typed_text(ax, typed_text, page_bg, default_ink=default_ink)
            typed_text_placed = True
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
