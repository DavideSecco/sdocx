//! OpenSdocx — shared Scene model + builder + render functions.
//!
//! `Document -> PageScene` construction (RE-calibrated geometry: arrows, table
//! borders, contrast-ink, text layout) lives here so the Tauri backend and the
//! `opensdocx-cli` binary consume the exact same functions instead of two
//! independent implementations. Pure/data-only: no Tauri, no I/O beyond `sdocx`
//! parsing types.

use serde::Serialize;

pub mod png;
pub mod svg;
pub use png::svg_to_png;
pub use svg::{render_page_svg, MediaResolver};

#[derive(Serialize)]
pub struct SceneStroke {
    pub points: Vec<[f64; 2]>,
    pub color: Option<[u8; 3]>,
    pub width: f32,
    pub tapered: bool,
    pub tool_id: Option<u8>,
    /// Per-point pressure quantized to 0..=255, present only for tapered
    /// (ink-pen-category) strokes — flat tools render at constant width, so
    /// shipping their pressure channel would be dead payload.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pressures: Option<Vec<u8>>,
}

#[derive(Serialize)]
pub struct SceneImage {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub media_index: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub angle_deg: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub affine: Option<[f64; 6]>,
    /// Normalized source crop `[x, y, w, h]` when the image is cropped.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub crop: Option<[f64; 4]>,
}

/// One uniform-style piece of a text line. The worker measures and wraps these
/// with real font metrics (the one text step that can't be done here), then
/// draws text + highlight/underline/strikethrough decorations.
#[derive(Serialize)]
pub struct SceneTextSeg {
    pub text: String,
    /// Em size in page units.
    pub font: f64,
    pub bold: bool,
    pub italic: bool,
    pub underline: bool,
    pub strike: bool,
    /// Foreground color; `None` = contrast ink (the stored default #252525 is
    /// mapped to `None`, mirroring pysdocx's contrast fallback).
    pub color: Option<[u8; 3]>,
    pub highlight: Option<[u8; 3]>,
}

/// A paragraph's list/todo marker glyph, pre-selected and sized here; the
/// worker measures and reserves its width like any other segment (pysdocx
/// `_paragraph_prefix` + the prefix-emit block in `_render_rich_text`).
#[derive(Serialize)]
pub struct ScenePrefix {
    pub text: String,
    /// Bridged page-unit font size, like `SceneTextSeg::font`.
    pub font: f64,
    /// The SAME size, unbridged (raw matplotlib points). pysdocx's own
    /// prefix-gap formula (`prefix_text_w + prefix_pt*0.9`, floor
    /// `prefix_pt*2.4`) adds this raw point number directly to a page-unit
    /// glyph-width measurement — a pre-existing unit quirk in the reference
    /// renderer; kept byte-for-byte rather than "fixed" so the reserved gap
    /// matches pysdocx's (and thus the GT's) spacing exactly.
    pub pt: f64,
    /// Fixed Samsung document-body hanging indents. `None` keeps the
    /// glyph-measured bbox-local fallback used by page text boxes.
    pub marker_indent: Option<f64>,
    pub body_indent: Option<f64>,
    pub color: Option<[u8; 3]>,
}

/// Non-left paragraph alignment (pysdocx only ever shifts a paragraph that
/// already fits `max_width` unwrapped — see `SceneTextLine::align`'s doc).
#[derive(Serialize, Debug, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum SceneAlign {
    Center,
    Right,
}

#[derive(Serialize)]
pub struct SceneTextLine {
    /// This paragraph's own row height: the baseline-to-baseline advance
    /// used for every visual row it wraps into (pysdocx `rendered_line_h` /
    /// `_blank_advance`). Pagination's fit check uses this value alone —
    /// NOT `lead_gap`/`trail_gap` — matching pysdocx `_paginate_segments`,
    /// whose per-row `line_h` is this same pre-gap number.
    pub advance: f64,
    /// Extra gap added once, before this paragraph's first visual row
    /// (pysdocx `space_before * PARA_SPACE_UNIT`, added ahead of the
    /// paragraph's layout).
    pub lead_gap: f64,
    /// Extra gap added once, after this paragraph's last visual row
    /// (pysdocx `space_after * PARA_SPACE_UNIT`, added once the paragraph's
    /// lines are laid out).
    pub trail_gap: f64,
    /// Indent offset added to the block anchor's x for every visual row of
    /// this paragraph, page units (pysdocx `indent * 70`).
    pub x_offset: f64,
    /// This paragraph's own available width before its list-prefix (if any)
    /// is subtracted: `SceneText::wrap_width - x_offset`, floored at
    /// `SceneText::min_width` (pysdocx `line_max_width`).
    pub max_width: f64,
    /// `None` = left (pysdocx default). The worker applies this only when
    /// the paragraph's plain text already fits `max_width` (after the
    /// prefix is subtracted) without wrapping — a paragraph that wraps
    /// never centers/right-aligns in pysdocx either.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub align: Option<SceneAlign>,
    /// List/todo marker, when this paragraph is a list item.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prefix: Option<ScenePrefix>,
    /// Empty for a blank line (the advance/gaps still apply).
    pub segs: Vec<SceneTextSeg>,
}

/// A rich text block with layout fully resolved here in the Scene builder
/// (anchor/wrap/rotation per pysdocx `_text_box_layout`); only glyph
/// measurement — and thus the actual wrap points — happens in the worker.
#[derive(Serialize)]
pub struct SceneText {
    /// Logical top-left origin of the (unrotated) text flow, page coords.
    pub anchor: [f64; 2],
    /// Max line width in page units before wrapping.
    pub wrap_width: f64,
    /// Clockwise rotation applied around `anchor`, degrees.
    pub angle_deg: f64,
    /// This block's plain (non-bold/italic) font size, bridged to page units
    /// like `SceneTextSeg::font`. Used by the worker only to measure whether
    /// a paragraph's alignment shift applies (pysdocx measures the alignment
    /// pre-check at this same plain base size, not per-run sizes).
    pub base_font: f64,
    /// `base fontpt * 4` in the same mixed-unit convention as
    /// `SceneTextLine::max_width` (pysdocx's wrap-width floor), reused by the
    /// worker after subtracting a measured list-prefix width.
    pub min_width: f64,
    pub lines: Vec<SceneTextLine>,
    /// Present only for the document-level typed note body: the flow spans the
    /// whole note and is split into page-height bands (pysdocx `paginate_typed_text`).
    /// This block is attached to EVERY page; the worker draws only the band whose
    /// index == `slot`, so overflow flows onto the following pages instead of
    /// running off the bottom of page 0.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub paginate: Option<ScenePaginate>,
}

/// Pagination band assignment for the typed note body (see `SceneText::paginate`).
#[derive(Serialize)]
pub struct ScenePaginate {
    /// 0-based page band this scene should draw (equals the page index).
    pub slot: usize,
    /// Uniform page height used to split the flow into bands, page units
    /// (pysdocx uses the anchor page's height for every band).
    pub band_height: f64,
}

// ⚠ Render heuristics, NOT format facts (docs/format/heuristics.md "Grid template
// pitches"): which built-in template ids are squared grids, their pitch, origin and
// line style are corpus constants calibrated against the GT photos — mirrored from
// pysdocx (page.py GRID_TEMPLATE_IDS/GRID_SPACING_BY_ID/GRID_ORIGIN, render.py
// GRID_COLOR/draw_grid). They live here in the Scene builder — not in the sdocx
// crate — so every frontend draws from the same numbers (risk ② in docs/app/README.md).
//
// ⚠ Heuristic unit bridge: pysdocx line widths are matplotlib POINTS; in its page
// figure (9×12 in, default subplot margins, equal aspect on a 1600×2262 page) one
// point maps to 3.40 page units. Reusing that factor here makes the app's line
// widths land where pysdocx's do.
pub const MPL_PT_TO_PAGE_UNITS: f64 = 3.40;

/// "Basic" built-in background category for a template id, or None if unknown (→ drawn plain).
/// Mirrors pysdocx `TEMPLATE_NAMES` (page.py): 1-3 line, 4-6 grid, 7-9 dot, 11 oxford.
pub fn template_category(id: u32) -> Option<&'static str> {
    match id {
        1..=3 => Some("line"),
        4..=6 => Some("grid"),
        7..=9 => Some("dot"),
        11 => Some("oxford"),
        _ => None,
    }
}
/// Line/grid share one narrow/default/wide pitch triple (72.5/102.5/168.0), measured from the
/// GT photos in samples/AllTypeofPageBasic/ (pysdocx GRID_SPACING_BY_ID / LINE_SPACING_BY_ID).
pub fn line_grid_spacing(id: u32) -> f64 {
    match id {
        1 | 4 => 72.5,
        3 | 6 => 168.0,
        _ => 102.5, // 2 | 5 (and any unmeasured fallback)
    }
}
/// Dot lattice pitch `(row, col)` — NOT square: columns run ~7-10% wider than rows at every id
/// (pysdocx DOT_SPACING_BY_ID, blob-centroid measurement).
pub fn dot_spacing(id: u32) -> (f64, f64) {
    match id {
        7 => (72.5, 79.7),
        9 => (168.0, 174.8),
        _ => (102.5, 110.0), // 8 (and fallback)
    }
}
/// Oxford (ruled + red margin): its own rule pitch + a single vertical margin rule (pysdocx
/// OXFORD_LINE_SPACING / OXFORD_MARGIN_X / OXFORD_MARGIN_COLOR).
pub const OXFORD_LINE_SPACING: f64 = 65.5;
pub const OXFORD_MARGIN_X: f64 = 235.0;
pub const OXFORD_MARGIN_COLOR: [u8; 3] = [0xe0, 0xa8, 0xa8];
/// Page coords of the first vertical/horizontal line: verticals flush at x=0, horizontals ~44px
/// down (the template's top margin). Shared by all built-in categories (pysdocx GRID_ORIGIN).
pub const GRID_ORIGIN: [f64; 2] = [0.0, 44.0];
/// Blue-gray of the Samsung rule/grid/dot templates. Deliberately DARKER than the GT-photo tint
/// (grid ~#d3dae8 / dots ~#b7bfce) at the user's request (2026-07-10) — true-to-photo is too faint
/// to read on screen. Kept in sync with pysdocx render.py GRID_COLOR/DOT_COLOR.
pub const GRID_COLOR: [u8; 3] = [0xa6, 0xaf, 0xca];
pub const DOT_COLOR: [u8; 3] = [0x8f, 0x98, 0xb0];
/// pysdocx draws rules at 0.6 matplotlib points (render.py draw_grid).
pub const GRID_LINE_WIDTH: f64 = 0.6 * MPL_PT_TO_PAGE_UNITS;
/// Dot radius in page units (pysdocx draws scatter s≈1.6 pt² ≈ this radius once bridged).
pub const DOT_RADIUS: f64 = 2.2;

#[derive(Serialize)]
pub struct SceneTemplate {
    pub id: u32,
    /// grid | line | dot | oxford | pdf | plain — the worker draws per this.
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin: Option<[f64; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub color: Option<[u8; 3]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line_width: Option<f64>,
    /// Horizontal-rule pitch (grid/line/dot/oxford).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub row_spacing: Option<f64>,
    /// Vertical-rule / dot-column pitch (grid/dot only; line/oxford have no verticals).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub col_spacing: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dot_radius: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub margin_x: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub margin_color: Option<[u8; 3]>,
    /// PDF-backed templates (Academic / imported PDF): which embedded PDF + which page. The
    /// worker still needs a rasteriser to draw these; the link is carried so it can.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pdf_media_index: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pdf_page_index: Option<u32>,
    /// Basename of an embedded custom-image template, resolved lazily by the UI.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image_filename: Option<String>,
}

/// An ellipse resolved from its 8 stored boundary points (pysdocx
/// `ellipse_from_points`): opposite points 0/4 and 2/6 are the axis endpoints.
#[derive(Serialize)]
pub struct SceneEllipse {
    pub cx: f64,
    pub cy: f64,
    pub rx: f64,
    pub ry: f64,
    pub rotation_deg: f64,
}

/// A rounded-rect resolved from its 4 stored edge midpoints (pysdocx
/// `oriented_corners`: corner_i = m_i + m_{i+1} − centroid). `radius` is the
/// corner radius (pysdocx pads its box style by min(w,h)·0.25).
#[derive(Serialize)]
pub struct SceneRoundRect {
    pub cx: f64,
    pub cy: f64,
    pub w: f64,
    pub h: f64,
    pub rotation_deg: f64,
    pub radius: f64,
}

/// One segment of a shape outline's true vector path, ported 1:1 from the decoded
/// stroke (no flattening) — lets the worker draw a real Bezier instead of a
/// polyline approximation. Mirrors `sdocx::OutlineOp`; only shapes with a curved
/// segment (heart, freeform-smooth) actually contain a `C` op — everything else
/// is `M` + a run of `L`s, equivalent to (and replacing) a flattened polyline.
#[derive(Serialize)]
#[serde(tag = "op")]
pub enum SceneOutlineOp {
    #[serde(rename = "M")]
    MoveTo { p: [f64; 2] },
    #[serde(rename = "L")]
    LineTo { p: [f64; 2] },
    #[serde(rename = "C")]
    CurveTo { c1: [f64; 2], c2: [f64; 2], p: [f64; 2] },
}

/// One inserted shape, geometry fully resolved here in the Scene builder (single
/// source of render heuristics — risk ② in docs/app/README.md): the worker only
/// strokes paths / native primitives.
#[derive(Serialize)]
pub struct SceneShape {
    pub kind: String,
    /// Outline polyline in page coords; empty when `ellipse`/`round_rect`/`outline`
    /// is set instead.
    pub points: Vec<[f64; 2]>,
    pub color: Option<[u8; 3]>,
    /// Stroke width in page units (pysdocx lw = max(pen_width/2.5, 1.0) points).
    pub width: f64,
    pub closed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ellipse: Option<SceneEllipse>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub round_rect: Option<SceneRoundRect>,
    /// True vector outline, preferred over `points` when present (see
    /// `SceneOutlineOp`).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outline: Option<Vec<SceneOutlineOp>>,
    /// Arrowhead triangles (filled), already sized/oriented.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub heads: Vec<[[f64; 2]; 3]>,
}

/// One table cell, fully resolved: position, final font size (shrink-to-fit
/// already applied), style, background fill, and under/strike flags (the worker
/// measures the glyphs to draw those lines over the text, not the whole cell).
#[derive(Serialize)]
pub struct SceneTableCell {
    /// Column index (into the parent table's `x_edges`), for the fill rect.
    pub col: usize,
    /// Row index (into the parent table's `y_edges`), for the fill rect.
    pub row: usize,
    /// Text start x (cell left edge + padding), page units.
    pub x: f64,
    /// Vertical center of the cell row, page units (draw middle-aligned).
    pub y: f64,
    pub text: String,
    /// Em size in page units.
    pub font: f64,
    pub bold: bool,
    pub italic: bool,
    /// Foreground; `None` = contrast ink.
    pub color: Option<[u8; 3]>,
    /// Cell background fill (explicit `fill_argb`, or the theme fill on a
    /// header/"evidenzia" cell); `None` = no fill.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill: Option<[u8; 3]>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub underline: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub strikethrough: bool,
}

/// One border block reduced for rendering: colour + which edges/lines are on +
/// corner radius (page units). Mirrors pysdocx `_table_border`.
#[derive(Serialize)]
pub struct SceneTableBorder {
    pub color: [u8; 3],
    /// Left+right edges (outer) / inner vertical lines are drawn.
    pub has_v: bool,
    /// Top+bottom edges (outer) / inner horizontal lines are drawn.
    pub has_h: bool,
    /// Rounded-corner radius (outer frame only); 0 = square.
    pub radius: f64,
}

/// A table resolved to its decoded borders + positioned cells (pysdocx
/// `render_table`). `outer` is the frame, `inner` the grid lines.
#[derive(Serialize)]
pub struct SceneTable {
    pub x_edges: Vec<f64>,
    pub y_edges: Vec<f64>,
    pub outer: SceneTableBorder,
    pub inner: SceneTableBorder,
    /// Border line width in page units.
    pub line_width: f64,
    pub cells: Vec<SceneTableCell>,
}

/// A collapsed sticky-note (attached sub-note) placement. The attachment is a
/// nested `.sdocx` that is not rendered recursively; the worker draws the
/// collapsed square (bg fill + dashed border + label), mirroring pysdocx's
/// "at least enumerate them" bar with the decoded bg color on top.
#[derive(Serialize)]
pub struct SceneSticky {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub media_index: usize,
    pub bg_color: Option<[u8; 3]>,
}

#[derive(Serialize)]
pub struct PageScene {
    pub width: u32,
    pub height: u32,
    /// Paper (background) fill color, RE-decoded from the `.page` header
    /// (`sdocx::Page::background_color`; every page carries one). Default white
    /// if ever absent.
    pub paper: [u8; 3],
    /// Ink for content with NO stored color (or color == paper), resolved here in
    /// Rust (single source) from the paper luminance — NOT the old bogus "dark
    /// mode" flag. Mirrors pysdocx `_contrast_ink` (white on dark paper, dark on
    /// light). Content that HAS a stored color is drawn with that color literally
    /// (see `inkFor` in the worker), so a dark-inked note on a dark paper stays
    /// dark-on-dark — faithful to Samsung (verified: the `Nera` note's strokes are
    /// stored `(37,37,37)`, drawn dark on `#010101`, not flipped to white).
    pub default_ink: [u8; 3],
    pub template: Option<SceneTemplate>,
    pub strokes: Vec<SceneStroke>,
    pub images: Vec<SceneImage>,
    pub shapes: Vec<SceneShape>,
    pub texts: Vec<SceneText>,
    pub sticky_notes: Vec<SceneSticky>,
    pub tables: Vec<SceneTable>,
}

/// ⚠ Render heuristic (pysdocx `_contrast_ink`): legible default ink for a paper
/// color — near-black on light paper, white on dark. The 140 luminance threshold
/// and the `#1a1a1a` near-black match the app's existing ink.
pub fn contrast_ink(paper: [u8; 3]) -> [u8; 3] {
    let [r, g, b] = paper;
    let luminance = 0.299 * r as f64 + 0.587 * g as f64 + 0.114 * b as f64;
    if luminance > 140.0 {
        [0x1a, 0x1a, 0x1a]
    } else {
        [0xff, 0xff, 0xff]
    }
}


pub fn color_arr(c: &sdocx::Color) -> [u8; 3] {
    [c.r, c.g, c.b]
}

/// pysdocx SHAPE_TYPES names — the Scene keeps the same vocabulary so renders can
/// be compared 1:1.
pub fn shape_kind_name(kind: sdocx::ShapeKind) -> &'static str {
    use sdocx::ShapeKind::*;
    match kind {
        Ellipse => "ellipse",
        Triangle => "triangle",
        Rectangle => "rectangle",
        Hexagon => "hexagon",
        Rhombus => "rhombus",
        Trapezoid => "trapezoid",
        Pentagon => "pentagon",
        Star => "star",
        Cross => "cross",
        Heart => "heart",
        RoundedRect => "rounded_rect",
        Freeform => "freeform",
        FreeformSmooth => "freeform_smooth",
        Arrow => "arrow",
        Polygon => "polygon",
    }
}

/// One filled arrowhead triangle: tip at `tip`, pointing away from `from`.
/// ⚠ Heuristic sizing mirroring pysdocx's matplotlib arrows (render.py:
/// `mutation_scale = 8 + lw*3`, arrowstyle "-|>" ≈ head length 0.4·scale,
/// half-width 0.2·scale, in points) — eyeballed against the GT, not a format fact.
pub fn arrow_head(tip: [f64; 2], from: [f64; 2], lw_pt: f64) -> [[f64; 2]; 3] {
    let (dx, dy) = (tip[0] - from[0], tip[1] - from[1]);
    let len = dx.hypot(dy).max(1e-9);
    let (ux, uy) = (dx / len, dy / len);
    let scale_units = (8.0 + 3.0 * lw_pt) * MPL_PT_TO_PAGE_UNITS;
    let head_len = (0.4 * scale_units).min(len); // never longer than the shaft
    let half_w = 0.2 * scale_units;
    let (bx, by) = (tip[0] - ux * head_len, tip[1] - uy * head_len);
    let (px, py) = (-uy, ux);
    [
        tip,
        [bx + px * half_w, by + py * half_w],
        [bx - px * half_w, by - py * half_w],
    ]
}

pub fn build_scene_shape(s: &sdocx::Shape) -> SceneShape {
    // pysdocx render_shape: lw = max((pen_width or 6.35) / 2.5, 1.0) matplotlib pt.
    let lw_pt = f64::max(s.pen_width.unwrap_or(6.35) as f64 / 2.5, 1.0);
    let mut points: Vec<[f64; 2]> = s.points.iter().map(|p| [p.x, p.y]).collect();
    let mut ellipse = None;
    let mut round_rect = None;
    let mut heads = Vec::new();

    match s.kind {
        // 8 boundary points: opposite points 0/4 and 2/6 are the axis endpoints.
        sdocx::ShapeKind::Ellipse if points.len() >= 7 => {
            let n = points.len() as f64;
            let (cx, cy) = points
                .iter()
                .fold((0.0, 0.0), |(ax, ay), p| (ax + p[0] / n, ay + p[1] / n));
            let a = [points[0][0] - points[4][0], points[0][1] - points[4][1]];
            let b = [points[2][0] - points[6][0], points[2][1] - points[6][1]];
            ellipse = Some(SceneEllipse {
                cx,
                cy,
                rx: a[0].hypot(a[1]) / 2.0,
                ry: b[0].hypot(b[1]) / 2.0,
                rotation_deg: a[1].atan2(a[0]).to_degrees(),
            });
            points = Vec::new();
        }
        // 4 edge midpoints → oriented corners (corner_i = m_i + m_{i+1} − centroid).
        sdocx::ShapeKind::RoundedRect if points.len() >= 4 => {
            let m = &points[..4];
            let (cx, cy) = (
                m.iter().map(|p| p[0]).sum::<f64>() / 4.0,
                m.iter().map(|p| p[1]).sum::<f64>() / 4.0,
            );
            let corner =
                |i: usize, j: usize| [m[i][0] + m[j][0] - cx, m[i][1] + m[j][1] - cy];
            let (c0, c2, c3) = (corner(0, 1), corner(2, 3), corner(3, 0));
            let e_w = [c0[0] - c3[0], c0[1] - c3[1]];
            let e_h = [c2[0] - c3[0], c2[1] - c3[1]];
            let (w, h) = (e_w[0].hypot(e_w[1]), e_h[0].hypot(e_h[1]));
            round_rect = Some(SceneRoundRect {
                cx,
                cy,
                w,
                h,
                rotation_deg: e_w[1].atan2(e_w[0]).to_degrees(),
                radius: w.min(h) * 0.25,
            });
            points = Vec::new();
        }
        sdocx::ShapeKind::Arrow if points.len() == 2 => {
            if s.head_start {
                heads.push(arrow_head(points[0], points[1], lw_pt));
            }
            if s.head_end {
                heads.push(arrow_head(points[1], points[0], lw_pt));
            }
        }
        _ => {}
    }

    // Prefer the true vector outline over the flattened polyline when the parser
    // found one (everything except ellipse/rounded-rect/arrow) — draws real curves
    // for heart/freeform-smooth and is a strictly smaller payload either way.
    let outline = s.outline.as_ref().map(|ops| {
        ops.iter()
            .map(|op| match op {
                sdocx::OutlineOp::MoveTo(p) => SceneOutlineOp::MoveTo { p: [p.x, p.y] },
                sdocx::OutlineOp::LineTo(p) => SceneOutlineOp::LineTo { p: [p.x, p.y] },
                sdocx::OutlineOp::CurveTo(c1, c2, p) => SceneOutlineOp::CurveTo {
                    c1: [c1.x, c1.y],
                    c2: [c2.x, c2.y],
                    p: [p.x, p.y],
                },
            })
            .collect()
    });
    if outline.is_some() {
        points = Vec::new();
    }

    SceneShape {
        kind: shape_kind_name(s.kind).to_string(),
        points,
        color: s.color.as_ref().map(color_arr),
        width: lw_pt * MPL_PT_TO_PAGE_UNITS,
        closed: s.closed,
        ellipse,
        round_rect,
        outline,
        heads,
    }
}

// ⚠ Render heuristics, NOT format facts — the text-box layout constants mirror
// pysdocx render.py (render_page's text-box path + _text_box_layout +
// TYPED_TEXT_*): font scale 1.36 Samsung-units→matplotlib-pt, 12pt floor,
// line height 3.2·font (36 floor), blank-line height 2·font (24 floor),
// 8px inner padding, 18px wrap inset on rotated frames, and the typed-note
// anchor (64, 80). Document-body line boxes use the controlled-PDF model below;
// glyph sizes still reuse the calibrated pt→page-units bridge.
pub const TEXT_DEFAULT_COLOR: [u8; 3] = [37, 37, 37];
pub const TEXT_BOX_FRAME_WRAP_INSET: f64 = 18.0;
pub const TYPED_TEXT_X0: f64 = 64.0;
pub const TYPED_TEXT_Y0: f64 = 80.0;
pub const TYPED_TEXT_FONTPT: f64 = 17.0;
pub const TYPED_TEXT_LINE_H: f64 = 66.0;
pub const TYPED_TEXT_BLANK_H: f64 = 66.0;
/// Exact Samsung typed-note transform grounded by the controlled vector PDFs:
/// stored font -> PDF font is 5/3 and PDF -> page units is 8/3.
pub const TYPED_TEXT_FONT_TO_PAGE: f64 = 40.0 / 9.0;
pub const TYPED_TEXT_DEFAULT_LINE_SPACING: f64 = 1.35;
pub const TYPED_TEXT_NUMBER_BODY_INDENT: f64 = 80.0;
pub const TYPED_TEXT_LIST_BODY_INDENT: f64 = 116.0;
pub const TYPED_TEXT_BULLET_MARKER_INDENT: f64 = 40.0;
pub const TYPED_TEXT_TODO_MARKER_INDENT: f64 = 24.0;
/// Checkbox controls impose a taller minimum than an ordinary 11pt text row.
pub const TYPED_TEXT_TODO_MIN_H: f64 = (77.76 + 75.99) / 2.0;
/// pysdocx `PARA_SPACE_UNIT`: converts a paragraph's decoded `space_before`/
/// `space_after` into page units.
pub const PARA_SPACE_UNIT: f64 = 5.0;
/// pysdocx `TODO_DONE_COLOR`: a checked todo's text (and its checkbox glyph)
/// forces this gray unless the run already carries an explicit color.
pub const TODO_DONE_COLOR: [u8; 3] = [150, 150, 150];

/// pysdocx `_paragraph_spacing`: a paragraph's decoded `line_spacing` (already
/// range-validated by `structural_paragraphs`) as a multiplier on the block's
/// base row height; unset means the neutral 1.0.
pub fn paragraph_spacing(p: &sdocx::ParagraphInfo) -> f64 {
    match p.line_spacing {
        Some(s) => s as f64 / 1.35,
        None => 1.0,
    }
}

/// pysdocx `_line_advance`.
pub fn line_advance(line_h: f64, p: &sdocx::ParagraphInfo, line_fontpt: f64, fontpt: f64) -> f64 {
    let sized = line_h * f64::max(line_fontpt / fontpt, 1.0);
    f64::max(sized * paragraph_spacing(p), line_fontpt * 2.25)
}

/// pysdocx `_blank_advance`.
pub fn blank_advance(blank_h: f64, p: &sdocx::ParagraphInfo) -> f64 {
    blank_h * paragraph_spacing(p)
}

/// Exact document-body line-box advance. Text boxes retain the separate
/// bbox-calibrated model above because they are not document-flow rows.
pub fn typed_note_advance(raw_font_size: f64, p: &sdocx::ParagraphInfo) -> f64 {
    let spacing = p
        .line_spacing
        .map(f64::from)
        .filter(|s| s.is_finite() && *s > 0.0)
        .unwrap_or(TYPED_TEXT_DEFAULT_LINE_SPACING);
    let advance = raw_font_size * TYPED_TEXT_FONT_TO_PAGE * spacing;
    if matches!(p.list, Some(sdocx::ListItem::Todo { .. })) {
        f64::max(advance, TYPED_TEXT_TODO_MIN_H)
    } else {
        advance
    }
}

/// pysdocx `_paragraph_prefix`: the list/todo marker text, when this
/// paragraph is a list item.
pub fn paragraph_prefix_text(p: &sdocx::ParagraphInfo) -> Option<String> {
    match p.list {
        Some(sdocx::ListItem::Numbered { number }) => Some(format!("{number}. ")),
        Some(sdocx::ListItem::Bullet) => Some("\u{2022} ".to_string()),
        Some(sdocx::ListItem::Todo { checked: true }) => Some("\u{2611} ".to_string()),
        Some(sdocx::ListItem::Todo { checked: false }) => Some("\u{2610} ".to_string()),
        None => None,
    }
}

/// pysdocx `_is_checked_todo`.
pub fn is_checked_todo(p: &sdocx::ParagraphInfo) -> bool {
    matches!(p.list, Some(sdocx::ListItem::Todo { checked: true }))
}

/// Anchor/wrap parameters resolved from the box bbox + rotation
/// (pysdocx `_text_box_layout`).
pub fn text_box_layout(tb: &sdocx::RichTextBox) -> ([f64; 2], f64) {
    let (x0, y0, x1, y1) = (tb.bbox.x_min, tb.bbox.y_min, tb.bbox.x_max, tb.bbox.y_max);
    let angle = tb.rotation_degrees.unwrap_or(0.0).rem_euclid(360.0);
    let box_w = f64::max(x1 - x0 - 16.0, 1.0);
    let box_h = f64::max(y1 - y0 - 16.0, 1.0);

    // Stored frame edge-midpoints give the exact logical origin and
    // half-extents of a rotated frame; the bbox-only branches are fallbacks.
    if let (Some(pts), true) = (tb.frame_midpoints, angle != 0.0) {
        let cx = pts.iter().map(|p| p.x).sum::<f64>() / 4.0;
        let cy = pts.iter().map(|p| p.y).sum::<f64>() / 4.0;
        let theta = angle.to_radians();
        let (ux, uy) = (theta.cos(), theta.sin());
        let (vx, vy) = (-theta.sin(), theta.cos());
        let half = |ax: f64, ay: f64| {
            pts.iter()
                .map(|p| ((p.x - cx) * ax + (p.y - cy) * ay).abs())
                .fold(0.0, f64::max)
        };
        let (half_w, half_h) = (half(ux, uy), half(vx, vy));
        if half_w > 1.0 && half_h > 1.0 {
            let near_vertical = (angle - 90.0).abs() <= 15.0 || (angle - 270.0).abs() <= 15.0;
            let wrap_inset = if near_vertical {
                0.0
            } else {
                f64::min(TEXT_BOX_FRAME_WRAP_INSET, half_w - 1.0)
            };
            return (
                [cx - ux * half_w - vx * half_h, cy - uy * half_w - vy * half_h],
                f64::max(half_w * 2.0 - 2.0 * wrap_inset, 1.0),
            );
        }
    }

    let vertical_wrap_w = f64::min(box_w, f64::max(box_h, box_h * 1.6));
    let vertical_anchor_pad = f64::min(f64::max(box_h * 0.1, 20.0), 36.0);
    if (angle - 90.0).abs() <= 15.0 {
        return ([x1 - vertical_anchor_pad, y0 + 8.0], vertical_wrap_w);
    }
    if (angle - 270.0).abs() <= 15.0 {
        return ([x0 + vertical_anchor_pad, y1 - 8.0], vertical_wrap_w);
    }
    ([x0 + 8.0, y0 + 8.0], box_w)
}

/// Resolve a rich text block into positioned, styled, pre-measured-height lines
/// (pysdocx `_render_rich_text`'s style expansion + line advances, minus the
/// glyph-metric wrapping, which the worker does). A zero-area bbox marks the
/// document-level typed note body, laid out from the page margins instead.
pub fn build_scene_text(tb: &sdocx::RichTextBox, page_width: f64) -> SceneText {
    let is_note_body = tb.bbox.x_max <= tb.bbox.x_min || tb.bbox.y_max <= tb.bbox.y_min;
    let (anchor, wrap_width, fontpt, line_h, blank_h) = if is_note_body {
        (
            [TYPED_TEXT_X0, TYPED_TEXT_Y0],
            page_width - TYPED_TEXT_X0,
            TYPED_TEXT_FONTPT,
            TYPED_TEXT_LINE_H,
            TYPED_TEXT_BLANK_H,
        )
    } else {
        let (anchor, wrap_width) = text_box_layout(tb);
        let fontpt = f64::max(tb.font_size.unwrap_or(11.0) as f64 * 1.36, 12.0);
        (
            anchor,
            wrap_width,
            fontpt,
            f64::max(fontpt * 3.2, 36.0),
            f64::max(fontpt * 2.0, 24.0),
        )
    };

    // Per-character style arrays (pysdocx `_char_styles`).
    let n = tb.text.chars().count();
    let mut bold = vec![false; n];
    let mut italic = vec![false; n];
    let mut underline = vec![false; n];
    let mut strike = vec![false; n];
    let mut color: Vec<Option<[u8; 3]>> = vec![None; n];
    let mut highlight: Vec<Option<[u8; 3]>> = vec![None; n];
    let mut font_raw: Vec<Option<f64>> = vec![None; n];
    for r in &tb.runs {
        for i in r.start..r.end.min(n) {
            bold[i] |= r.bold;
            italic[i] |= r.italic;
            underline[i] |= r.underline;
            strike[i] |= r.strikethrough;
        }
    }
    for c in &tb.colors {
        let rgb = [c.color.r, c.color.g, c.color.b];
        // The stored default color renders as contrast ink, not literally.
        if rgb != TEXT_DEFAULT_COLOR {
            for slot in color.iter_mut().take(c.end.min(n)).skip(c.start) {
                *slot = Some(rgb);
            }
        }
    }
    for h in &tb.highlights {
        for slot in highlight.iter_mut().take(h.end.min(n)).skip(h.start) {
            *slot = Some([h.color.r, h.color.g, h.color.b]);
        }
    }
    for f in &tb.font_sizes {
        for slot in font_raw.iter_mut().take(f.end.min(n)).skip(f.start) {
            *slot = Some(f.size as f64);
        }
    }

    let chars: Vec<char> = tb.text.chars().collect();
    let default_paragraph = sdocx::ParagraphInfo::default();
    let mut lines = Vec::new();
    let mut gi = 0usize;
    for (para_idx, line) in tb.text.split('\n').enumerate() {
        let len = line.chars().count();
        let paragraph = tb.paragraphs.get(para_idx).unwrap_or(&default_paragraph);
        let checked_todo = is_checked_todo(paragraph);
        let x_offset = paragraph.indent as f64 * 70.0;
        let max_width = f64::max(wrap_width - x_offset, fontpt * 4.0);
        let align = match paragraph.alignment {
            sdocx::Alignment::Center => Some(SceneAlign::Center),
            sdocx::Alignment::Right => Some(SceneAlign::Right),
            sdocx::Alignment::Left => None,
        };
        let lead_gap = paragraph.space_before as f64 * PARA_SPACE_UNIT;
        let trail_gap = paragraph.space_after as f64 * PARA_SPACE_UNIT;
        let default_raw = tb.font_size.unwrap_or(11.0) as f64;

        if len == 0 {
            let raw = font_raw.get(gi).copied().flatten().unwrap_or(default_raw);
            lines.push(SceneTextLine {
                advance: if is_note_body {
                    typed_note_advance(raw, paragraph)
                } else {
                    blank_advance(blank_h, paragraph)
                },
                lead_gap,
                trail_gap,
                x_offset,
                max_width,
                align,
                prefix: None,
                segs: Vec::new(),
            });
            gi += 1;
            continue;
        }
        // Line advance scales with the largest per-run font on the line
        // (pysdocx `_line_advance`).
        let line_raw = (gi..gi + len)
            .filter_map(|i| font_raw.get(i).copied().flatten())
            .fold(default_raw, f64::max);
        let line_fontpt = f64::max(line_raw * 1.36, fontpt);
        let advance = if is_note_body {
            typed_note_advance(line_raw, paragraph)
        } else {
            line_advance(line_h, paragraph, line_fontpt, fontpt)
        };

        // List/todo marker: sized at the paragraph's own font (pysdocx draws it
        // at `para_font_raw * 1.36`, i.e. the same already-bridged value stored
        // in `font_pt`), so it matches its list text instead of the block's base size.
        let prefix = paragraph_prefix_text(paragraph).map(|text| {
            let prefix_raw = (gi..gi + len)
                .filter_map(|i| font_raw.get(i).copied().flatten())
                .next()
                .unwrap_or(default_raw);
            let prefix_pt = prefix_raw * 1.36;
            let (marker_indent, body_indent) = if is_note_body {
                let scale = prefix_raw / 11.0;
                match paragraph.list {
                    Some(sdocx::ListItem::Numbered { .. }) => {
                        (Some(0.0), Some(TYPED_TEXT_NUMBER_BODY_INDENT * scale))
                    }
                    Some(sdocx::ListItem::Bullet) => (
                        Some(TYPED_TEXT_BULLET_MARKER_INDENT * scale),
                        Some(TYPED_TEXT_LIST_BODY_INDENT * scale),
                    ),
                    Some(sdocx::ListItem::Todo { .. }) => (
                        Some(TYPED_TEXT_TODO_MARKER_INDENT * scale),
                        Some(TYPED_TEXT_LIST_BODY_INDENT * scale),
                    ),
                    None => (None, None),
                }
            } else {
                (None, None)
            };
            ScenePrefix {
                text,
                font: prefix_pt * MPL_PT_TO_PAGE_UNITS,
                pt: prefix_pt,
                marker_indent,
                body_indent,
                color: checked_todo.then_some(TODO_DONE_COLOR),
            }
        });

        // Group consecutive equal-style characters into segments. A checked
        // todo forces strikethrough + gray (unless a color is already set) on
        // its whole paragraph (pysdocx `checked_todo` style override).
        let mut segs = Vec::new();
        let mut i = 0usize;
        while i < len {
            let style_at = |k: usize| {
                (
                    bold[gi + k],
                    italic[gi + k],
                    underline[gi + k],
                    strike[gi + k] || checked_todo,
                    if checked_todo { Some(color[gi + k].unwrap_or(TODO_DONE_COLOR)) } else { color[gi + k] },
                    highlight[gi + k],
                    font_raw[gi + k].map(|v| v.to_bits()),
                )
            };
            let here = style_at(i);
            let mut j = i + 1;
            while j < len && style_at(j) == here {
                j += 1;
            }
            let seg_fontpt = font_raw[gi + i].map(|raw| raw * 1.36).unwrap_or(fontpt);
            segs.push(SceneTextSeg {
                text: chars[gi + i..gi + j].iter().collect(),
                font: seg_fontpt * MPL_PT_TO_PAGE_UNITS,
                bold: here.0,
                italic: here.1,
                underline: here.2,
                strike: here.3,
                color: here.4,
                highlight: here.5,
            });
            i = j;
        }
        lines.push(SceneTextLine {
            advance,
            lead_gap,
            trail_gap,
            x_offset,
            max_width,
            align,
            prefix,
            segs,
        });
        gi += len + 1;
    }

    SceneText {
        anchor,
        wrap_width,
        base_font: fontpt * MPL_PT_TO_PAGE_UNITS,
        min_width: fontpt * 4.0,
        angle_deg: tb.rotation_degrees.unwrap_or(0.0).rem_euclid(360.0),
        lines,
        paginate: None,
    }
}

// ⚠ Render heuristics, NOT format facts — table drawing constants mirror
// pysdocx render.py `render_table`: 1.2pt border line, 18px cell padding, 15pt
// default font with a shrink-to-fit approximation. Border colour/width/radius and
// which edges are on now come from the decoded border blocks, not a constant.
pub const TABLE_LINE_COLOR: [u8; 3] = [0x8A, 0x8F, 0x9A];
pub const TABLE_FONTPT: f64 = 15.0;
pub const TABLE_PAD: f64 = 18.0;
/// The header/"evidenzia" ink (foreground_color ff3a3a3d): such cells get the
/// theme fill behind them (Samsung's highlighted rows/columns).
pub const TABLE_HEADER_INK: sdocx::Color = sdocx::Color { r: 0x3A, g: 0x3A, b: 0x3D };

pub fn argb_rgb(argb: u32) -> [u8; 3] {
    [(argb >> 16) as u8, (argb >> 8) as u8, argb as u8]
}

/// Reduce a 4-entry border block to `(has_v, has_h, color, radius)` (pysdocx
/// `_table_border`): entries 0/2 vertical, 1/3 horizontal; on == opaque + width>0.
pub fn table_border_model(block: &[sdocx::TableBorder; 4]) -> SceneTableBorder {
    let on = |e: &sdocx::TableBorder| e.argb >> 24 != 0 && e.width > 0.0;
    let has_v = on(&block[0]);
    let has_h = on(&block[1]);
    let color = block.iter().find(|e| on(e)).map_or(TABLE_LINE_COLOR, |e| argb_rgb(e.argb));
    let radius = if has_v {
        block[0].radius_x as f64
    } else if has_h {
        block[1].radius_x as f64
    } else {
        0.0
    };
    SceneTableBorder { color, has_v, has_h, radius }
}

/// Build a Scene table from the byte-exact structural table (`sdocx::NoteTable`).
/// Geometry is page-local (`NoteTable::grid`); cell text/style/fill and the outer
/// frame + inner grid all come from the decoded object. Mirrors pysdocx
/// `structural_table_render_model` + `render_table`.
pub fn build_scene_table(t: &sdocx::NoteTable) -> SceneTable {
    let (x_edges, y_edges) = t.grid();
    let theme_fill = argb_rgb(t.theme_fill_argb);
    let cells = t
        .cells
        .iter()
        .filter(|c| c.col + 1 < x_edges.len() && c.row + 1 < y_edges.len())
        .map(|c| {
            let style = c.whole_cell_style();
            let x0 = x_edges[c.col];
            let x1 = x_edges[c.col + 1];
            let cx = x0 + TABLE_PAD;
            let cy = (y_edges[c.row] + y_edges[c.row + 1]) / 2.0;
            let text = c.text.trim_end_matches('\n').to_string();
            // No cap: an explicitly larger cell (e.g. size 20) renders larger.
            let base_pt = style.font_size.map(f64::from).unwrap_or(TABLE_FONTPT);
            let usable = f64::max(x1 - x0 - 2.0 * TABLE_PAD, 1.0);
            let approx_width = text.chars().count().max(1) as f64 * base_pt * 7.0;
            let cell_fontpt = f64::max(5.5, f64::min(base_pt, base_pt * usable / approx_width));
            let rgb = style.color.as_ref().map(color_arr).filter(|&v| v != TEXT_DEFAULT_COLOR);
            // Explicit fill, else the theme fill on a header/"evidenzia" cell.
            let fill = if c.fill_argb >> 24 != 0 {
                Some(argb_rgb(c.fill_argb))
            } else if style.color == Some(TABLE_HEADER_INK) {
                Some(theme_fill)
            } else {
                None
            };
            SceneTableCell {
                col: c.col,
                row: c.row,
                x: cx,
                y: cy,
                text,
                font: cell_fontpt * MPL_PT_TO_PAGE_UNITS,
                bold: style.bold,
                italic: style.italic,
                color: rgb,
                fill,
                underline: style.underline,
                strikethrough: style.strikethrough,
            }
        })
        .collect();
    let outer = table_border_model(&t.outer_borders);
    let mut inner = table_border_model(&t.grid_borders);
    // Inner lines borrow the outer colour when the grid block is fully off.
    if t.grid_borders.iter().all(|e| e.argb >> 24 == 0) {
        inner.color = outer.color;
    }
    SceneTable {
        x_edges,
        y_edges,
        outer,
        inner,
        line_width: 1.2 * MPL_PT_TO_PAGE_UNITS,
        cells,
    }
}

pub fn build_page_scene(page: &sdocx::Page) -> PageScene {
    let strokes = page
        .strokes
        .iter()
        .map(|s| SceneStroke {
            points: s.points.iter().map(|p| [p.x, p.y]).collect(),
            color: s.color.as_ref().map(color_arr),
            width: s.pen_width,
            tapered: s.tapered,
            tool_id: s.tool_id,
            pressures: (s.tapered && !s.pressures.is_empty()).then(|| {
                s.pressures
                    .iter()
                    .map(|&p| (p.clamp(0.0, 1.0) * 255.0).round() as u8)
                    .collect()
            }),
        })
        .collect();

    let mut images = Vec::new();
    let mut shapes = Vec::new();
    let mut texts = Vec::new();
    let mut sticky_notes = Vec::new();
    for el in &page.elements {
        match el {
            sdocx::PageElement::Shape(s) => shapes.push(build_scene_shape(s)),
            sdocx::PageElement::Image {
                bbox,
                media_index,
                angle_deg,
                affine_transform,
                crop,
            } => images.push(SceneImage {
                x: bbox.x_min,
                y: bbox.y_min,
                w: bbox.x_max - bbox.x_min,
                h: bbox.y_max - bbox.y_min,
                media_index: *media_index,
                angle_deg: *angle_deg,
                affine: affine_transform.map(|a| [a.a, a.b, a.c, a.d, a.e, a.f]),
                crop: crop.map(|c| [c.x, c.y, c.w, c.h]),
            }),
            sdocx::PageElement::TextBox(tb) => {
                texts.push(build_scene_text(tb, page.width as f64))
            }
            sdocx::PageElement::StickyNote {
                bbox,
                media_index,
                bg_color,
            } => sticky_notes.push(SceneSticky {
                x: bbox.x_min,
                y: bbox.y_min,
                w: bbox.x_max - bbox.x_min,
                h: bbox.y_max - bbox.y_min,
                media_index: *media_index,
                bg_color: bg_color.as_ref().map(color_arr),
            }),
        }
    }

    let template = page.template.as_ref().map(|t| {
        let category = match &t.source {
            sdocx::PageTemplateSource::CustomPdf { .. } => "pdf",
            sdocx::PageTemplateSource::CustomImage { .. } => "image",
            sdocx::PageTemplateSource::BuiltIn => template_category(t.id).unwrap_or("plain"),
        };
        let mut st = SceneTemplate {
            id: t.id,
            kind: category.into(),
            origin: None,
            color: None,
            line_width: None,
            row_spacing: None,
            col_spacing: None,
            dot_radius: None,
            margin_x: None,
            margin_color: None,
            pdf_media_index: None,
            pdf_page_index: None,
            image_filename: None,
        };
        match category {
            "grid" => {
                let s = line_grid_spacing(t.id);
                st.origin = Some(GRID_ORIGIN);
                st.color = Some(GRID_COLOR);
                st.line_width = Some(GRID_LINE_WIDTH);
                st.row_spacing = Some(s);
                st.col_spacing = Some(s); // square
            }
            "line" => {
                st.origin = Some(GRID_ORIGIN);
                st.color = Some(GRID_COLOR);
                st.line_width = Some(GRID_LINE_WIDTH);
                st.row_spacing = Some(line_grid_spacing(t.id)); // horizontal rules only
            }
            "dot" => {
                let (row, col) = dot_spacing(t.id);
                st.origin = Some(GRID_ORIGIN);
                st.color = Some(DOT_COLOR);
                st.row_spacing = Some(row);
                st.col_spacing = Some(col);
                st.dot_radius = Some(DOT_RADIUS);
            }
            "oxford" => {
                st.origin = Some(GRID_ORIGIN);
                st.color = Some(GRID_COLOR);
                st.line_width = Some(GRID_LINE_WIDTH);
                st.row_spacing = Some(OXFORD_LINE_SPACING);
                st.margin_x = Some(OXFORD_MARGIN_X);
                st.margin_color = Some(OXFORD_MARGIN_COLOR);
            }
            "pdf" => {
                if let sdocx::PageTemplateSource::CustomPdf {
                    media_index,
                    page_index,
                } = &t.source
                {
                    st.pdf_media_index = Some(*media_index);
                    st.pdf_page_index = Some(*page_index);
                }
            }
            "image" => {
                if let sdocx::PageTemplateSource::CustomImage { filename } = &t.source {
                    st.image_filename = Some(filename.clone());
                }
            }
            _ => {}
        }
        st
    });

    let paper = page.background_color.as_ref().map(color_arr).unwrap_or([255, 255, 255]);
    PageScene {
        width: page.width,
        height: page.height,
        paper,
        default_ink: contrast_ink(paper),
        template,
        strokes,
        images,
        shapes,
        texts,
        sticky_notes,
        tables: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn sample(name: &str) -> Option<sdocx::Reader<std::fs::File>> {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../samples").join(name);
        if !path.exists() {
            eprintln!("skipping: {name} not present");
            return None;
        }
        Some(sdocx::open(&path).expect("open sample"))
    }

    fn scene(reader: &mut sdocx::Reader<std::fs::File>, index: usize) -> PageScene {
        let bytes = reader.page_bytes(index).expect("page bytes");
        let page = sdocx::parse_page(&bytes).expect("parse page");
        build_page_scene(&page)
    }

    /// `contrast_ink` mirrors pysdocx `_contrast_ink`: near-black on light paper,
    /// white on dark.
    #[test]
    fn contrast_ink_by_luminance() {
        assert_eq!(contrast_ink([252, 252, 252]), [0x1a, 0x1a, 0x1a]); // white paper
        assert_eq!(contrast_ink([245, 221, 221]), [0x1a, 0x1a, 0x1a]); // pink paper
        assert_eq!(contrast_ink([37, 37, 37]), [0xff, 0xff, 0xff]); // dark paper
    }


    /// The Scene resolves paper + default_ink per page from the RE-decoded `.page`
    /// paper color (NOT the bogus dark-mode flag): the `Rosina` pink sample proves
    /// the light path (dark ink), and the `Nera` black-paper sample proves the dark
    /// path — luminance flips the ink to white automatically.
    #[test]
    fn scene_resolves_paper_and_ink() {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../samples/test-background");
        let cases = [
            ("Rosina-Liscio_260709_125531.sdocx", [245, 221, 221], [0x1a, 0x1a, 0x1a]),
            ("Nera-Liscio_260709_140421.sdocx", [1, 1, 1], [0xff, 0xff, 0xff]),
        ];
        let mut checked = 0;
        for (name, paper, ink) in cases {
            let path = dir.join(name);
            if !path.exists() {
                eprintln!("skipping: {name} not present");
                continue;
            }
            let mut reader = sdocx::open(&path).expect("open sample");
            for i in 0..reader.page_count() {
                let sc = scene(&mut reader, i);
                assert_eq!(sc.paper, paper, "{name} paper page {i}");
                assert_eq!(sc.default_ink, ink, "{name} ink page {i}");
                checked += 1;
            }
        }
        if checked == 0 {
            eprintln!("no test-background samples present");
        }
    }

    /// The squared sample uses built-in template id 4 → grid at 72.5 pitch.
    #[test]
    fn squared_template_resolves_to_grid() {
        let Some(mut reader) = sample("OnlyTextTypeWritten_squared_260703_013624.sdocx") else {
            return;
        };
        let scene = scene(&mut reader, 0);
        let t = scene.template.expect("template present");
        assert_eq!((t.id, t.kind.as_str()), (4, "grid"));
        assert_eq!(t.row_spacing, Some(72.5));
        assert_eq!(t.col_spacing, Some(72.5)); // grid is square
        assert_eq!(t.origin, Some(GRID_ORIGIN));
        assert_eq!(t.color, Some(GRID_COLOR));
    }

    #[test]
    fn custom_image_template_reaches_scene() {
        let Some(mut reader) = sample("PagLiscia&templatescustoms_260711_122117.sdocx") else {
            return;
        };
        let scene = scene(&mut reader, 1);
        let template = scene.template.expect("custom image template");
        assert_eq!((template.id, template.kind.as_str()), (12, "image"));
        assert_eq!(
            template.image_filename.as_deref(),
            Some("files_231229_092644_140.jpg")
        );
    }

    /// The Basic-templates sample cycles every built-in id — spot-check one per category resolves
    /// to the right kind + pitch (line/dot/oxford were previously dropped to "plain" = blank).
    #[test]
    fn basic_templates_resolve_per_category() {
        let Some(mut reader) = sample("AlltypeofPageBasic_260709_200911.sdocx") else {
            return;
        };
        // Archive/page order: page 2 = Lined (id 2), page 6 = Grid wide (id 6), page 8 = Dot (id 8),
        // page 11 = Oxford (id 11). Resolve by id rather than assuming an index.
        let mut seen = std::collections::HashMap::new();
        for i in 0..reader.page_count() {
            if let Some(t) = scene(&mut reader, i).template {
                seen.entry(t.id).or_insert((t.kind.clone(), t.row_spacing, t.col_spacing, t.margin_x));
            }
        }
        assert_eq!(seen[&2].0, "line");
        assert_eq!(seen[&2].1, Some(102.5));
        assert_eq!(seen[&2].2, None); // line: no verticals
        assert_eq!(seen[&6].0, "grid");
        assert_eq!(seen[&6].1, Some(168.0));
        assert_eq!(seen[&8].0, "dot");
        assert_eq!(seen[&8].1, Some(102.5));
        assert_eq!(seen[&8].2, Some(110.0)); // dot: non-square
        assert_eq!(seen[&11].0, "oxford");
        assert_eq!(seen[&11].3, Some(OXFORD_MARGIN_X));
    }

    /// The shapes sample carries every family; the Scene must resolve geometry:
    /// ellipses/rounded-rects as native primitives, arrows with prebuilt heads,
    /// everything else as an outline polyline. Totals match pysdocx (see the
    /// sdocx crate's shapes parity test).
    #[test]
    fn shapes_scene_resolves_geometry() {
        let Some(mut reader) = sample("OnlyShapesblack_new_260701_185935.sdocx") else {
            return;
        };
        let mut total = 0usize;
        let (mut ellipses, mut round_rects, mut single_heads, mut double_heads) = (0, 0, 0, 0);
        let mut curved_outlines = 0usize;
        for i in 0..reader.page_count() {
            for s in &scene(&mut reader, i).shapes {
                total += 1;
                assert!(s.width >= 1.0 * MPL_PT_TO_PAGE_UNITS, "width floor");
                match s.kind.as_str() {
                    "ellipse" => {
                        let e = s.ellipse.as_ref().expect("ellipse resolved");
                        assert!(e.rx > 0.0 && e.ry > 0.0 && s.points.is_empty());
                        ellipses += 1;
                    }
                    "rounded_rect" => {
                        let r = s.round_rect.as_ref().expect("round rect resolved");
                        assert!(r.w > 0.0 && r.h > 0.0 && r.radius > 0.0 && s.points.is_empty());
                        round_rects += 1;
                    }
                    "arrow" => {
                        assert_eq!(s.points.len(), 2);
                        assert!(s.outline.is_none(), "arrows have no path");
                        match s.heads.len() {
                            0 => {} // plain line (no arrowheads)
                            1 => single_heads += 1,
                            2 => double_heads += 1,
                            n => panic!("arrow with {n} heads"),
                        }
                    }
                    // Every other family now draws from the true outline (§ B2b:
                    // the flattened `points` polyline is only a fallback).
                    _ => {
                        let ops = s.outline.as_ref().expect("outline resolved");
                        assert!(ops.len() >= 2 && s.points.is_empty(), "outline present, points cleared");
                        if ops.iter().any(|op| matches!(op, SceneOutlineOp::CurveTo { .. })) {
                            curved_outlines += 1;
                        }
                    }
                }
            }
        }
        // Totals from pysdocx on this sample (see tests/fixtures in crates/sdocx).
        assert_eq!(total, 207);
        assert_eq!(ellipses, 35);
        assert_eq!(round_rects, 3);
        // heart (5) + freeform_smooth (19) are the only families whose stored path
        // contains a real CubicBezierTo segment.
        assert_eq!(curved_outlines, 24);
        // 3 single arrows + 2 double arrows on the lines/arrows page (the other
        // 24 "arrow" objects are plain lines with no heads).
        assert_eq!((single_heads, double_heads), (3, 2));
    }

    /// The text sample carries 3 boxes: horizontal, 16°-rotated, and a
    /// 90°-vertical one with a bold run (chars 37..47) and an italic run
    /// (52..59). The Scene must expose resolved layout + styled segments.
    #[test]
    fn text_boxes_scene_resolves_layout_and_styles() {
        let Some(mut reader) = sample("OnlyTextTypeWritten_260701_180427.sdocx") else {
            return;
        };
        let page_idx = (0..reader.page_count())
            .find(|&i| !scene(&mut reader, i).texts.is_empty())
            .expect("a page with text boxes");
        let texts = scene(&mut reader, page_idx).texts;
        assert_eq!(texts.len(), 3);

        for t in &texts {
            assert!(t.wrap_width > 1.0, "wrap width resolved");
            assert!(!t.lines.is_empty());
            for line in &t.lines {
                assert!(line.advance > 0.0);
            }
            // Default 11-unit font → 14.96pt → page units via the pt bridge.
            let seg = t.lines.iter().flat_map(|l| &l.segs).next().expect("segs");
            let expected_font = 11.0 * 1.36 * MPL_PT_TO_PAGE_UNITS;
            assert!((seg.font - expected_font).abs() < 1e-6, "font {}", seg.font);
        }

        let vertical = texts
            .iter()
            .find(|t| (t.angle_deg - 90.0).abs() < 0.01)
            .expect("90° box");
        // Bold 37..47 and italic 52..59 split the flow into styled segments.
        let flat: String = vertical
            .lines
            .iter()
            .flat_map(|l| &l.segs)
            .map(|s| s.text.as_str())
            .collect::<Vec<_>>()
            .join("");
        let bold_text: String = vertical
            .lines
            .iter()
            .flat_map(|l| &l.segs)
            .filter(|s| s.bold)
            .map(|s| s.text.as_str())
            .collect();
        let italic_text: String = vertical
            .lines
            .iter()
            .flat_map(|l| &l.segs)
            .filter(|s| s.italic)
            .map(|s| s.text.as_str())
            .collect();
        let chars: Vec<char> = flat.chars().collect();
        assert_eq!(bold_text, chars[37..47].iter().collect::<String>());
        assert_eq!(italic_text, chars[52..59].iter().collect::<String>());

        // The rotated boxes resolve their anchor from the stored frame
        // midpoints: the anchor must sit inside a page-sized region, not at
        // the raw bbox corner.
        let rotated = texts
            .iter()
            .find(|t| (t.angle_deg - 16.0).abs() < 0.5)
            .expect("16° box");
        assert!(rotated.anchor[0].is_finite() && rotated.anchor[1].is_finite());
    }

    /// The typed note body carries every paragraph-layout feature this sample
    /// exercises: numbered/bullet/todo list markers, center/right alignment, and
    /// left indent — ported from pysdocx `common_frame_paragraphs`. Assert each
    /// survives into the Scene (`SceneTextLine`), not just the run-level styling
    /// `text_boxes_scene_resolves_layout_and_styles` already covers.
    #[test]
    fn typed_note_body_scene_resolves_paragraphs() {
        let Some(mut reader) = sample("OnlyTextTypeWritten_260701_180427.sdocx") else {
            return;
        };
        let note_text = reader.metadata().note_text.clone().expect("typed note body");
        let (width, _) = reader.page_size(0).expect("page 0 size");
        let st = build_scene_text(&note_text, width as f64);

        let line_text = |l: &SceneTextLine| -> String { l.segs.iter().map(|s| s.text.as_str()).collect() };
        let find = |needle: &str| -> &SceneTextLine {
            st.lines
                .iter()
                .find(|l| line_text(l) == needle)
                .unwrap_or_else(|| panic!("missing line {needle:?}"))
        };

        assert_eq!(find("elenco numerato 2").prefix.as_ref().expect("numbered prefix").text, "2. ");
        let numbered = find("elenco numerato 2").prefix.as_ref().expect("numbered prefix");
        assert_eq!((numbered.marker_indent, numbered.body_indent), (Some(0.0), Some(80.0)));
        let bullet = find("elenco puntato1").prefix.as_ref().expect("bullet prefix");
        assert_eq!(bullet.text, "\u{2022} ");
        assert_eq!((bullet.marker_indent, bullet.body_indent), (Some(40.0), Some(116.0)));
        let todo_done = find("todo3-fatta");
        let todo_prefix = todo_done.prefix.as_ref().expect("todo prefix");
        assert_eq!(todo_prefix.text, "\u{2611} ");
        assert_eq!((todo_prefix.marker_indent, todo_prefix.body_indent), (Some(24.0), Some(116.0)));
        assert!(todo_done.segs.iter().all(|s| s.strike), "a checked todo strikes its own text");

        assert_eq!(find("testo al centro").align, Some(SceneAlign::Center));
        assert_eq!(find("testo a dx").align, Some(SceneAlign::Right));
        assert_eq!(find("testo rientrato da sx di 1").x_offset, 70.0);
        assert_eq!(find("testo rientrato da sx di 2").x_offset, 140.0);

        // Headings carry decoded space_before/space_after, giving them extra
        // breathing room the plain paragraphs around them don't have.
        let heading = find("questo è heading 1");
        assert!(heading.lead_gap > 0.0 && heading.trail_gap > 0.0, "heading spacing");
        let plain = find("Testo normale scritto carattere 11");
        assert_eq!((plain.lead_gap, plain.trail_gap), (0.0, 0.0));
        assert!((plain.advance - 66.0).abs() < 1e-9);
        assert!((todo_done.advance - TYPED_TEXT_TODO_MIN_H).abs() < 1e-9);
    }

    /// End-to-end guard for the structural Common projection used by the app,
    /// not merely the pre-normalized Python render model.
    #[test]
    fn all_samsung_scene_drops_object_padding_and_limits_strike() {
        let Some(mut reader) = sample("Allsamsungnotes_260630_113259.sdocx") else {
            return;
        };
        let note_text = reader.metadata().note_text.clone().expect("typed note body");
        let (width, _) = reader.page_size(4).expect("page 4 size");
        let st = build_scene_text(&note_text, width as f64);
        let line_text = |line: &SceneTextLine| -> String {
            line.segs.iter().map(|seg| seg.text.as_str()).collect()
        };

        assert_eq!(line_text(&st.lines[0]),
            "Testo scritto a tastiera. Grassetto corsivo sottolineato cancellato");
        assert!(st.lines.iter().all(|line| !line_text(line).contains('\u{FFFC}')));
        let struck: Vec<_> = st.lines.iter().flat_map(|line| &line.segs)
            .filter(|seg| seg.strike).map(|seg| seg.text.as_str()).collect();
        assert_eq!(struck, ["cancellato"]);
    }

    /// The 4×3 structural table resolves to page-local grid edges + 12
    /// positioned cells with shrink-to-fit fonts; it lands on its own page
    /// (`page_index` == 3 for this sample).
    #[test]
    fn table_scene_resolves_cells() {
        let Some(reader) = sample("Allsamsungnotes_260630_113259.sdocx") else {
            return;
        };
        let tables = reader.metadata().note_tables.clone();
        assert_eq!(tables.len(), 1);
        assert_eq!(tables[0].page_index(), 3);
        let st = build_scene_table(&tables[0]);
        assert_eq!((st.x_edges.len(), st.y_edges.len()), (4, 5));
        assert_eq!(st.cells.len(), 12);
        for cell in &st.cells {
            assert!(cell.font > 0.0);
            assert!(cell.x > st.x_edges[0] && cell.x < st.x_edges[3]);
            assert!(cell.y > st.y_edges[0] && cell.y < st.y_edges[4]);
            // The stored default gray maps to None (contrast ink).
            assert_eq!(cell.color, None);
        }
    }
}
