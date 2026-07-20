//! `PageScene -> SVG` rendering, headless (no webview/canvas). Ports the *draw*
//! step of `opensdocx/src/render.worker.ts` 1:1 so exported files match the
//! on-screen renderer.
//!
//! Scope: background, built-in templates (grid/line/dot/oxford — PDF/custom-
//! image templates are not yet rasterized here), images, ink strokes
//! (tapered + plain), shapes, sticky-note placeholders, rich text
//! (`crate::text`) and tables (`crate::table`). Rich text/table glyph
//! metrics come from a bundled font (`crate::font`) rather than the
//! worker's OS `sans-serif` — a deliberate, accepted divergence for
//! deterministic export output (see the round-2 export plan).

use crate::{PageScene, SceneOutlineOp, SceneShape, SceneStroke, SceneTemplate};
use base64::Engine as _;
use std::fmt::Write as _;

/// Resolves a `media_index` to its (mime type, raw bytes), so the renderer
/// stays free of any `Reader`/I/O dependency — the caller (Tauri command or
/// CLI) already has this from `sdocx::Reader::media_bytes`/`media_asset`.
/// `&mut self`: `sdocx::Reader::media_bytes` seeks the archive, so resolving
/// is inherently a mutable operation.
pub trait MediaResolver {
    fn resolve(&mut self, media_index: usize) -> Option<(String, Vec<u8>)>;
}

impl<F: FnMut(usize) -> Option<(String, Vec<u8>)>> MediaResolver for F {
    fn resolve(&mut self, media_index: usize) -> Option<(String, Vec<u8>)> {
        self(media_index)
    }
}

pub(crate) fn n(v: f64) -> String {
    // Fixed-point, not scientific notation — friendlier to SVG parsers
    // (resvg included) than Rust's default `{}` Display for small floats.
    let s = format!("{v:.3}");
    // Trim trailing zeros but keep at least one decimal digit's worth of
    // sanity (cheap cosmetic cleanup, not load-bearing for correctness).
    if let Some(stripped) = s.strip_suffix("000") {
        stripped.trim_end_matches('.').to_string()
    } else {
        s
    }
}

pub(crate) fn css(c: [u8; 3]) -> String {
    format!("rgb({},{},{})", c[0], c[1], c[2])
}

/// Mirrors the worker's `inkFor`: a piece of content draws in its own color
/// unless that color is absent or equals the paper, in which case it takes
/// the paper-contrast ink resolved by the Scene builder.
pub(crate) fn ink_for(color: Option<[u8; 3]>, paper: [u8; 3], default_ink: [u8; 3]) -> String {
    match color {
        Some(c) if c != paper => css(c),
        _ => css(default_ink),
    }
}

pub(crate) fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// One smooth path over `points[from..=to]`, quadratic through segment
/// midpoints — byte-for-byte the same construction as the worker's
/// `strokePath` (Catmull-Rom-ish smoothing via consecutive-midpoint quads).
fn stroke_path_d(points: &[[f64; 2]], from: usize, to: usize) -> String {
    let mut d = format!("M{} {}", n(points[from][0]), n(points[from][1]));
    if to - from == 1 {
        let _ = write!(d, " L{} {}", n(points[to][0]), n(points[to][1]));
        return d;
    }
    for i in from + 1..to {
        let mx = (points[i][0] + points[i + 1][0]) / 2.0;
        let my = (points[i][1] + points[i + 1][1]) / 2.0;
        let _ = write!(
            d,
            " Q{} {} {} {}",
            n(points[i][0]),
            n(points[i][1]),
            n(mx),
            n(my)
        );
    }
    let _ = write!(d, " L{} {}", n(points[to][0]), n(points[to][1]));
    d
}

fn draw_background(out: &mut String, scene: &PageScene) {
    let _ = write!(
        out,
        r#"<rect x="0" y="0" width="{}" height="{}" fill="{}"/>"#,
        n(scene.width as f64),
        n(scene.height as f64),
        css(scene.paper)
    );
}

/// Built-in "Basic" background template: grid/line/dot/oxford. PDF and
/// custom-image templates are skipped here (need a rasterizer, not yet
/// wired into the headless renderer).
fn draw_template(out: &mut String, scene: &PageScene, tpl: &SceneTemplate) {
    let (Some([ox, oy]), Some(rows)) = (tpl.origin, tpl.row_spacing) else {
        return;
    };
    let w = scene.width as f64;
    let h = scene.height as f64;
    match tpl.kind.as_str() {
        "dot" => {
            let Some(cols) = tpl.col_spacing else { return };
            let r = tpl.dot_radius.unwrap_or(2.0);
            let fill = tpl.color.map(css).unwrap_or_else(|| "#8f98b0".to_string());
            let _ = write!(out, r#"<g fill="{fill}">"#);
            let mut y = oy.rem_euclid(rows);
            while y <= h + 0.5 {
                let mut x = ox.rem_euclid(cols);
                while x <= w + 0.5 {
                    let _ = write!(out, r#"<circle cx="{}" cy="{}" r="{}"/>"#, n(x), n(y), n(r));
                    x += cols;
                }
                y += rows;
            }
            out.push_str("</g>");
        }
        "grid" | "line" | "oxford" => {
            let mut d = String::new();
            if tpl.kind == "grid" {
                if let Some(cols) = tpl.col_spacing {
                    let mut x = ox.rem_euclid(cols);
                    while x <= w + 0.5 {
                        let _ = write!(d, "M{} 0L{} {} ", n(x), n(x), n(h));
                        x += cols;
                    }
                }
            }
            let mut y = oy.rem_euclid(rows);
            while y <= h + 0.5 {
                let _ = write!(d, "M0 {}L{} {} ", n(y), n(w), n(y));
                y += rows;
            }
            let stroke = tpl.color.map(css).unwrap_or_else(|| "#a6afca".to_string());
            let lw = tpl.line_width.unwrap_or(2.0);
            let _ = write!(
                out,
                r#"<path d="{}" stroke="{stroke}" stroke-width="{}" fill="none"/>"#,
                d.trim_end(),
                n(lw)
            );
            if tpl.kind == "oxford" {
                if let Some(mx) = tpl.margin_x {
                    let mcolor = tpl.margin_color.map(css).unwrap_or_else(|| "#e0a8a8".to_string());
                    let _ = write!(
                        out,
                        r#"<line x1="{}" y1="0" x2="{}" y2="{}" stroke="{mcolor}" stroke-width="{}"/>"#,
                        n(mx),
                        n(mx),
                        n(h),
                        n(lw * 1.6)
                    );
                }
            }
        }
        _ => {}
    }
}

fn draw_images(out: &mut String, scene: &PageScene, media: &mut dyn MediaResolver) {
    for im in &scene.images {
        let Some((mime, bytes)) = media.resolve(im.media_index) else {
            continue;
        };
        let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
        let href = format!("data:{mime};base64,{b64}");

        // Destination box before any crop adjustment.
        let (mut dx, mut dy, mut dw, mut dh) = (im.x, im.y, im.w, im.h);
        let mut clip = None;
        if let Some(crop) = im.crop {
            let [cx, cy, cw, ch] = crop;
            // Same derivation as canvas drawImage(sx,sy,sw,sh,dx,dy,dw,dh) with a
            // normalized source rect: placing the FULL image at the scale implied
            // by the crop, offset so the cropped sub-rect lands on the original
            // destination box, then clipping to that box. Depends only on the
            // normalized crop fractions, not the source image's pixel size.
            let full_w = im.w / cw.max(1e-9);
            let full_h = im.h / ch.max(1e-9);
            let full_x = im.x - cx * full_w;
            let full_y = im.y - cy * full_h;
            clip = Some((im.x, im.y, im.w, im.h));
            dx = full_x;
            dy = full_y;
            dw = full_w;
            dh = full_h;
        }

        let clip_id = clip.map(|_| format!("imgclip{}", im.media_index));
        if let (Some((cx, cy, cw, ch)), Some(id)) = (clip, &clip_id) {
            let _ = write!(
                out,
                r#"<clipPath id="{id}"><rect x="{}" y="{}" width="{}" height="{}"/></clipPath>"#,
                n(cx),
                n(cy),
                n(cw),
                n(ch)
            );
        }

        let transform = if let Some([a, b, c, d, e, f]) = im.affine {
            format!(
                r#" transform="matrix({},{},{},{},{},{})""#,
                n(a),
                n(b),
                n(c),
                n(d),
                n(e),
                n(f)
            )
        } else if let Some(deg) = im.angle_deg.filter(|d| *d != 0.0) {
            let cx = im.x + im.w / 2.0;
            let cy = im.y + im.h / 2.0;
            format!(r#" transform="rotate({},{},{})""#, n(deg), n(cx), n(cy))
        } else {
            String::new()
        };
        let clip_attr = clip_id
            .as_ref()
            .map(|id| format!(r#" clip-path="url(#{id})""#))
            .unwrap_or_default();

        let _ = write!(
            out,
            r#"<image x="{}" y="{}" width="{}" height="{}" href="{href}" preserveAspectRatio="none"{transform}{clip_attr}/>"#,
            n(dx),
            n(dy),
            n(dw.max(0.0)),
            n(dh.max(0.0))
        );
    }
}

fn draw_strokes(out: &mut String, scene: &PageScene) {
    for s in &scene.strokes {
        draw_one_stroke(out, s, scene.paper, scene.default_ink);
    }
}

fn draw_one_stroke(out: &mut String, s: &SceneStroke, paper: [u8; 3], default_ink: [u8; 3]) {
    if s.points.is_empty() {
        return;
    }
    let base = f64::max(s.width as f64, 0.5);
    let color = ink_for(s.color, paper, default_ink);
    if s.points.len() == 1 {
        let [x, y] = s.points[0];
        let _ = write!(
            out,
            r#"<circle cx="{}" cy="{}" r="{}" fill="{color}"/>"#,
            n(x),
            n(y),
            n(base / 2.0)
        );
        return;
    }
    let common = r##"fill="none" stroke-linecap="round" stroke-linejoin="round""##;
    if s.tapered {
        if let Some(pressures) = &s.pressures {
            if !pressures.is_empty() {
                draw_tapered(out, s, pressures, base, &color, common);
                return;
            }
        }
    }
    let d = stroke_path_d(&s.points, 0, s.points.len() - 1);
    let _ = write!(
        out,
        r#"<path d="{d}" stroke="{color}" stroke-width="{}" {common}/>"#,
        n(base)
    );
}

/// Pressure-tapered ink: same width-bucketing as the worker's `drawTapered` —
/// consecutive segments whose width stays within a tolerance band share one
/// smooth sub-path, so a stroke becomes a handful of `<path>`s, not hundreds.
fn draw_tapered(out: &mut String, s: &SceneStroke, pressures: &[u8], base: f64, color: &str, common: &str) {
    let pts = &s.points;
    let width_at = |k: usize| {
        let p = pressures
            .get(k)
            .or(pressures.last())
            .copied()
            .unwrap_or(128) as f64;
        base * (0.3 + 0.7 * (p / 255.0))
    };
    let tol = f64::max(base * 0.12, 0.25);
    let mut from = 0usize;
    let mut group_w = width_at(0);
    for k in 1..pts.len() - 1 {
        let w = width_at(k);
        if (w - group_w).abs() > tol {
            let d = stroke_path_d(pts, from, k);
            let _ = write!(
                out,
                r#"<path d="{d}" stroke="{color}" stroke-width="{}" {common}/>"#,
                n(group_w)
            );
            from = k;
            group_w = w;
        }
    }
    let d = stroke_path_d(pts, from, pts.len() - 1);
    let _ = write!(
        out,
        r#"<path d="{d}" stroke="{color}" stroke-width="{}" {common}/>"#,
        n(group_w)
    );
}

fn draw_shapes(out: &mut String, scene: &PageScene) {
    for s in &scene.shapes {
        draw_one_shape(out, s, scene.paper, scene.default_ink);
    }
}

fn draw_one_shape(out: &mut String, s: &SceneShape, paper: [u8; 3], default_ink: [u8; 3]) {
    let color = ink_for(s.color, paper, default_ink);
    let lw = f64::max(s.width, 0.5);
    let common = format!(r#"stroke="{color}" stroke-width="{}" fill="none""#, n(lw));

    if let Some(e) = &s.ellipse {
        let _ = write!(
            out,
            r#"<ellipse cx="{}" cy="{}" rx="{}" ry="{}" transform="rotate({},{},{})" {common}/>"#,
            n(e.cx),
            n(e.cy),
            n(e.rx),
            n(e.ry),
            n(e.rotation_deg),
            n(e.cx),
            n(e.cy)
        );
    } else if let Some(r) = &s.round_rect {
        // `rotate(deg, cx, cy)` pivots WORLD space around (cx, cy) without
        // re-centering the origin, so the rect itself must be positioned in
        // world coordinates (centered on cx, cy) — matches the worker's
        // `translate(cx,cy); rotate(deg); rect(-w/2,-h/2,w,h)`.
        let _ = write!(
            out,
            r#"<rect x="{}" y="{}" width="{}" height="{}" rx="{}" ry="{}" transform="rotate({},{},{})" {common}/>"#,
            n(r.cx - r.w / 2.0),
            n(r.cy - r.h / 2.0),
            n(r.w),
            n(r.h),
            n(r.radius),
            n(r.radius),
            n(r.rotation_deg),
            n(r.cx),
            n(r.cy)
        );
    } else if let Some(ops) = &s.outline {
        if !ops.is_empty() {
            let mut d = String::new();
            for op in ops {
                match op {
                    SceneOutlineOp::MoveTo { p } => {
                        let _ = write!(d, "M{} {} ", n(p[0]), n(p[1]));
                    }
                    SceneOutlineOp::LineTo { p } => {
                        let _ = write!(d, "L{} {} ", n(p[0]), n(p[1]));
                    }
                    SceneOutlineOp::CurveTo { c1, c2, p } => {
                        let _ = write!(
                            d,
                            "C{} {} {} {} {} {} ",
                            n(c1[0]),
                            n(c1[1]),
                            n(c2[0]),
                            n(c2[1]),
                            n(p[0]),
                            n(p[1])
                        );
                    }
                }
            }
            if s.closed {
                d.push('Z');
            }
            let _ = write!(out, r#"<path d="{}" {common}/>"#, d.trim_end());
        }
    } else if s.points.len() >= 2 {
        let mut d = format!("M{} {} ", n(s.points[0][0]), n(s.points[0][1]));
        for p in &s.points[1..] {
            let _ = write!(d, "L{} {} ", n(p[0]), n(p[1]));
        }
        if s.closed {
            d.push('Z');
        }
        let _ = write!(out, r#"<path d="{}" {common}/>"#, d.trim_end());
    }

    for head in &s.heads {
        let _ = write!(
            out,
            r#"<polygon points="{},{} {},{} {},{}" fill="{color}"/>"#,
            n(head[0][0]),
            n(head[0][1]),
            n(head[1][0]),
            n(head[1][1]),
            n(head[2][0]),
            n(head[2][1])
        );
    }
}

fn draw_stickies(out: &mut String, scene: &PageScene) {
    for st in &scene.sticky_notes {
        let fill = st.bg_color.map(css).unwrap_or_else(|| "#ffe6ae".to_string());
        let _ = write!(
            out,
            r#"<rect x="{}" y="{}" width="{}" height="{}" fill="{fill}"/>"#,
            n(st.x),
            n(st.y),
            n(st.w),
            n(st.h)
        );
        let _ = write!(
            out,
            r##"<rect x="{}" y="{}" width="{}" height="{}" fill="none" stroke="#1a1a1a" stroke-width="{}" stroke-dasharray="10,8"/>"##,
            n(st.x),
            n(st.y),
            n(st.w),
            n(st.h),
            n(1.0 * 3.4)
        );
        let _ = write!(
            out,
            r##"<text x="{}" y="{}" font-size="{}" font-family="{}" fill="#1a1a1a" dominant-baseline="hanging">{}</text>"##,
            n(st.x + 6.0),
            n(st.y + 6.0),
            n(9.0 * 3.4),
            crate::font::FONT_FAMILY_NAME,
            xml_escape("sticky")
        );
    }
}

/// Self-contained `@font-face` block embedding the bundled font as base64
/// `truetype` data, so the SVG's text still renders correctly in an
/// external viewer that doesn't have DejaVu Sans installed. Confirmed with
/// a manual test (round-2 export plan, risk #4): a real headless Chromium,
/// sandboxed to have realistic system fonts but NOT DejaVu Sans, renders
/// this block's glyphs correctly (verified by comparing against a
/// deliberately-corrupted copy of the same SVG, which fell back to a
/// visibly different font) — so this genuinely achieves self-containment
/// for the primary "open the exported SVG in a browser" case.
/// **`resvg` itself does NOT use this block** (confirmed: `png::tests::
/// resvg_ignores_embedded_font_face_block`) — PNG rasterization instead
/// registers the bundled font directly into resvg's own `fontdb`
/// (`crate::font::register_into`), independent of this block entirely.
/// Gated on the caller only emitting it when the page actually has
/// text/tables, to avoid ~2.7MB of raw font data (~3.6MB base64'd, 4 styles)
/// on every text-free (ink/image/shape-only) page.
fn font_face_block(out: &mut String) {
    use crate::font::FontStyle;
    out.push_str("<defs><style>");
    for (style, weight, italic) in [
        (FontStyle::Regular, "normal", "normal"),
        (FontStyle::Bold, "bold", "normal"),
        (FontStyle::Italic, "normal", "italic"),
        (FontStyle::BoldItalic, "bold", "italic"),
    ] {
        let b64 = base64::engine::general_purpose::STANDARD.encode(crate::font::bytes_for(style));
        let _ = write!(
            out,
            "@font-face{{font-family:'{}';font-weight:{weight};font-style:{italic};src:url(data:font/ttf;base64,{b64}) format('truetype');}}",
            crate::font::FONT_FAMILY_NAME
        );
    }
    out.push_str("</style></defs>");
}

/// Renders one page's Scene to a standalone SVG document string. `media`
/// resolves a `media_index` to (mime, bytes) for `<image>` embedding; pass a
/// resolver that always returns `None` to render everything except images.
pub fn render_page_svg(scene: &PageScene, media: &mut dyn MediaResolver) -> String {
    let mut out = String::new();
    let _ = write!(
        out,
        r#"<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{}" height="{}" viewBox="0 0 {} {}" xml:space="preserve">"#,
        scene.width, scene.height, scene.width, scene.height
    );
    // xml:space="preserve" above: SVG/CSS default-collapses whitespace,
    // which would silently eat the literal spaces the text wrap pass below
    // relies on (e.g. a wrapped word's trailing space, list-prefix "1. ").
    if !scene.texts.is_empty() || !scene.tables.is_empty() {
        font_face_block(&mut out);
    }
    draw_background(&mut out, scene);
    if let Some(tpl) = &scene.template {
        draw_template(&mut out, scene, tpl);
    }
    draw_images(&mut out, scene, media);
    draw_strokes(&mut out, scene);
    draw_shapes(&mut out, scene);
    crate::text::draw_texts(&mut out, scene);
    crate::table::draw_tables(&mut out, scene);
    draw_stickies(&mut out, scene);
    out.push_str("</svg>");
    out
}
