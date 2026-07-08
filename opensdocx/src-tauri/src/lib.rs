//! OpenSdocx — Tauri backend.
//!
//! Parses a `.sdocx` with the `sdocx` core and exposes a lightweight, UI-agnostic
//! per-page `Scene` to the frontend. Rendering heuristics will grow in the Scene
//! builder (Phase 1); this Phase-0 slice carries strokes, images, and raw text.

use std::sync::Mutex;

use base64::Engine as _;
use serde::Serialize;
use tauri::State;

/// The currently loaded document, kept in Tauri-managed state so the frontend can
/// request pages lazily without re-parsing.
#[derive(Default)]
struct AppState {
    reader: Mutex<Option<sdocx::Reader<std::fs::File>>>,
}

#[derive(Serialize)]
struct DocMeta {
    page_count: usize,
    dark_mode: bool,
    background: Option<[u8; 3]>,
}

#[derive(Serialize)]
struct SceneStroke {
    points: Vec<[f64; 2]>,
    color: Option<[u8; 3]>,
    width: f32,
    tapered: bool,
    tool_id: Option<u8>,
    /// Per-point pressure quantized to 0..=255, present only for tapered
    /// (ink-pen-category) strokes — flat tools render at constant width, so
    /// shipping their pressure channel would be dead payload.
    #[serde(skip_serializing_if = "Option::is_none")]
    pressures: Option<Vec<u8>>,
}

#[derive(Serialize)]
struct SceneImage {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    media_index: usize,
}

#[derive(Serialize)]
struct SceneText {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    text: String,
    color: Option<[u8; 3]>,
    font_size: Option<f32>,
    rotation: Option<f64>,
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
const MPL_PT_TO_PAGE_UNITS: f64 = 3.40;
const GRID_SPACING_DEFAULT: f64 = 102.5;
/// Grid pitch per template id, measured from the 905px-wide GT photos (58px and
/// 41px cells scaled to the 1600-unit page). Unknown grid ids would fall back to
/// the default, but today only ids 4 and 5 classify as grids at all.
fn grid_spacing(id: u32) -> f64 {
    match id {
        4 => 72.5,
        5 => 102.5,
        _ => GRID_SPACING_DEFAULT,
    }
}
fn is_grid_template_id(id: u32) -> bool {
    matches!(id, 4 | 5)
}
/// Page coords of the first vertical/horizontal grid line: vertical lines start
/// flush at x=0, horizontal ones ~44px down (the template's top margin).
const GRID_ORIGIN: [f64; 2] = [0.0, 44.0];
/// Faint blue-gray of the Samsung squared template (pysdocx render.py GRID_COLOR).
const GRID_COLOR: [u8; 3] = [0xd3, 0xda, 0xe8];
/// pysdocx draws the grid at 0.6 matplotlib points (render.py draw_grid).
const GRID_LINE_WIDTH: f64 = 0.6 * MPL_PT_TO_PAGE_UNITS;

#[derive(Serialize)]
struct SceneTemplate {
    id: u32,
    kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    spacing: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    origin: Option<[f64; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    color: Option<[u8; 3]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    line_width: Option<f64>,
}

/// An ellipse resolved from its 8 stored boundary points (pysdocx
/// `ellipse_from_points`): opposite points 0/4 and 2/6 are the axis endpoints.
#[derive(Serialize)]
struct SceneEllipse {
    cx: f64,
    cy: f64,
    rx: f64,
    ry: f64,
    rotation_deg: f64,
}

/// A rounded-rect resolved from its 4 stored edge midpoints (pysdocx
/// `oriented_corners`: corner_i = m_i + m_{i+1} − centroid). `radius` is the
/// corner radius (pysdocx pads its box style by min(w,h)·0.25).
#[derive(Serialize)]
struct SceneRoundRect {
    cx: f64,
    cy: f64,
    w: f64,
    h: f64,
    rotation_deg: f64,
    radius: f64,
}

/// One segment of a shape outline's true vector path, ported 1:1 from the decoded
/// stroke (no flattening) — lets the worker draw a real Bezier instead of a
/// polyline approximation. Mirrors `sdocx::OutlineOp`; only shapes with a curved
/// segment (heart, freeform-smooth) actually contain a `C` op — everything else
/// is `M` + a run of `L`s, equivalent to (and replacing) a flattened polyline.
#[derive(Serialize)]
#[serde(tag = "op")]
enum SceneOutlineOp {
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
struct SceneShape {
    kind: String,
    /// Outline polyline in page coords; empty when `ellipse`/`round_rect`/`outline`
    /// is set instead.
    points: Vec<[f64; 2]>,
    color: Option<[u8; 3]>,
    /// Stroke width in page units (pysdocx lw = max(pen_width/2.5, 1.0) points).
    width: f64,
    closed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    ellipse: Option<SceneEllipse>,
    #[serde(skip_serializing_if = "Option::is_none")]
    round_rect: Option<SceneRoundRect>,
    /// True vector outline, preferred over `points` when present (see
    /// `SceneOutlineOp`).
    #[serde(skip_serializing_if = "Option::is_none")]
    outline: Option<Vec<SceneOutlineOp>>,
    /// Arrowhead triangles (filled), already sized/oriented.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    heads: Vec<[[f64; 2]; 3]>,
}

#[derive(Serialize)]
struct PageScene {
    width: u32,
    height: u32,
    background: Option<[u8; 3]>,
    template: Option<SceneTemplate>,
    strokes: Vec<SceneStroke>,
    images: Vec<SceneImage>,
    shapes: Vec<SceneShape>,
    texts: Vec<SceneText>,
}

#[derive(Serialize)]
struct MediaOut {
    mime: String,
    base64: String,
}

fn color_arr(c: &sdocx::Color) -> [u8; 3] {
    [c.r, c.g, c.b]
}

/// pysdocx SHAPE_TYPES names — the Scene keeps the same vocabulary so renders can
/// be compared 1:1.
fn shape_kind_name(kind: sdocx::ShapeKind) -> &'static str {
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
fn arrow_head(tip: [f64; 2], from: [f64; 2], lw_pt: f64) -> [[f64; 2]; 3] {
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

fn build_scene_shape(s: &sdocx::Shape) -> SceneShape {
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

fn build_page_scene(page: &sdocx::Page) -> PageScene {
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
    for el in &page.elements {
        match el {
            sdocx::PageElement::Shape(s) => shapes.push(build_scene_shape(s)),
            sdocx::PageElement::Image { bbox, media_index } => images.push(SceneImage {
                x: bbox.x_min,
                y: bbox.y_min,
                w: bbox.x_max - bbox.x_min,
                h: bbox.y_max - bbox.y_min,
                media_index: *media_index,
            }),
            sdocx::PageElement::TextBox(tb) => texts.push(SceneText {
                x: tb.bbox.x_min,
                y: tb.bbox.y_min,
                w: tb.bbox.x_max - tb.bbox.x_min,
                h: tb.bbox.y_max - tb.bbox.y_min,
                text: tb.text.clone(),
                color: tb.color.as_ref().map(color_arr),
                font_size: tb.font_size,
                rotation: tb.rotation_degrees,
            }),
        }
    }

    let template = page.template.map(|t| {
        let grid = matches!(t.source, sdocx::PageTemplateSource::BuiltIn) && is_grid_template_id(t.id);
        SceneTemplate {
            id: t.id,
            kind: match t.source {
                sdocx::PageTemplateSource::BuiltIn if grid => "grid".into(),
                sdocx::PageTemplateSource::BuiltIn => "plain".into(),
                sdocx::PageTemplateSource::CustomPdf { .. } => "pdf".into(),
            },
            spacing: grid.then(|| grid_spacing(t.id)),
            origin: grid.then_some(GRID_ORIGIN),
            color: grid.then_some(GRID_COLOR),
            line_width: grid.then_some(GRID_LINE_WIDTH),
        }
    });

    PageScene {
        width: page.width,
        height: page.height,
        background: page.background_color.as_ref().map(color_arr),
        template,
        strokes,
        images,
        shapes,
        texts,
    }
}

/// Open a `.sdocx` lazily (metadata + manifests only), cache the reader in state,
/// and return document metadata. Pages/media are decoded on demand below, so even
/// huge multi-page notes open instantly and cheaply.
#[tauri::command]
async fn open_document(path: String, state: State<'_, AppState>) -> Result<DocMeta, String> {
    let reader = sdocx::open(&path).map_err(|e| e.to_string())?;
    let meta = DocMeta {
        page_count: reader.page_count(),
        dark_mode: reader.metadata().dark_mode_compatibility.unwrap_or(false),
        background: reader.metadata().background_color.as_ref().map(color_arr),
    };
    *state.reader.lock().unwrap() = Some(reader);
    Ok(meta)
}

/// Parse and return the lightweight render scene for a single page (on demand).
///
/// The Reader mutex is held only while extracting the page's bytes from the ZIP;
/// the parse itself runs outside the lock, so concurrent page requests (scroll,
/// prefetch) parse in parallel instead of queueing on one page at a time.
#[tauri::command]
async fn get_page_scene(index: usize, state: State<'_, AppState>) -> Result<PageScene, String> {
    let (bytes, note_text, media_map) = {
        let mut guard = state.reader.lock().unwrap();
        let reader = guard.as_mut().ok_or("no document loaded")?;
        let bytes = reader.page_bytes(index).map_err(|e| e.to_string())?;
        // The typed note body renders as page 0's text layer (as Reader::page does).
        let note_text = (index == 0)
            .then(|| reader.metadata().note_text.clone())
            .flatten();
        (bytes, note_text, reader.media_index_map().clone())
    };
    let mut page = sdocx::parse_page(&bytes).map_err(|e| e.to_string())?;
    sdocx::remap_media_indices(&mut page, &media_map);
    if let Some(text) = note_text {
        page.elements.push(sdocx::PageElement::TextBox(text));
    }
    Ok(build_page_scene(&page))
}

/// Read every page's pixel size cheaply (headers only) for continuous-scroll layout.
#[tauri::command]
async fn get_page_sizes(state: State<'_, AppState>) -> Result<Vec<[u32; 2]>, String> {
    let mut guard = state.reader.lock().unwrap();
    let reader = guard.as_mut().ok_or("no document loaded")?;
    let n = reader.page_count();
    let mut sizes = Vec::with_capacity(n);
    for i in 0..n {
        let (w, h) = reader.page_size(i).map_err(|e| e.to_string())?;
        sizes.push([w, h]);
    }
    Ok(sizes)
}

/// Read one embedded media blob (on demand) and return it base64-encoded.
#[tauri::command]
async fn get_media(index: usize, state: State<'_, AppState>) -> Result<MediaOut, String> {
    let mut guard = state.reader.lock().unwrap();
    let reader = guard.as_mut().ok_or("no document loaded")?;
    let mime = reader
        .metadata()
        .media_assets
        .get(index)
        .map(|a| a.mime_type.clone())
        .ok_or("media index out of range")?;
    let bytes = reader.media_bytes(index).map_err(|e| e.to_string())?;
    // Pasted images are extensionless, so the name-derived mime can be wrong —
    // trust the magic bytes when they identify a known image format.
    let sniffed = match bytes.as_slice() {
        [0xFF, 0xD8, ..] => Some("image/jpeg"),
        [0x89, b'P', b'N', b'G', ..] => Some("image/png"),
        [b'R', b'I', b'F', b'F', _, _, _, _, b'W', b'E', b'B', b'P', ..] => Some("image/webp"),
        [b'G', b'I', b'F', b'8', ..] => Some("image/gif"),
        _ => None,
    };
    Ok(MediaOut {
        mime: sniffed.map(str::to_string).unwrap_or(mime),
        base64: base64::engine::general_purpose::STANDARD.encode(&bytes),
    })
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

    /// The squared sample uses built-in template id 4 → grid at 72.5 pitch.
    #[test]
    fn squared_template_resolves_to_grid() {
        let Some(mut reader) = sample("OnlyTextTypeWritten_squared_260703_013624.sdocx") else {
            return;
        };
        let scene = scene(&mut reader, 0);
        let t = scene.template.expect("template present");
        assert_eq!((t.id, t.kind.as_str()), (4, "grid"));
        assert_eq!(t.spacing, Some(72.5));
        assert_eq!(t.origin, Some(GRID_ORIGIN));
        assert_eq!(t.color, Some(GRID_COLOR));
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
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // WebKitGTK zooms the whole page on Ctrl+scroll and the DOM can't
            // cancel it, which would scale the toolbar too. Pin the webview zoom
            // to 100% so only the canvas (document) zoom, done in the frontend,
            // is ever visible.
            #[cfg(target_os = "linux")]
            {
                use gtk::gdk::EventType;
                use gtk::glib::Propagation;
                use gtk::prelude::WidgetExt;
                use tauri::Manager;
                use webkit2gtk::WebViewExt;
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.with_webview(|webview| {
                        let wv = webview.inner();
                        // Ctrl+scroll / Ctrl +/- change the WebKit zoom level: pin it to 100%.
                        wv.set_zoom_level(1.0);
                        wv.connect_zoom_level_notify(|wv| {
                            if (wv.zoom_level() - 1.0).abs() > 1e-6 {
                                wv.set_zoom_level(1.0);
                            }
                        });
                        // Touchpad pinch is handled natively (the DOM never sees it):
                        // swallow the GDK pinch event so WebKit can't pinch-zoom the UI.
                        // KNOWN LIMITATION: touch-SCREEN pinch uses a different GTK
                        // gesture path and is NOT caught here — it still zooms the UI.
                        // Accepted/deferred (see docs/app/README.md §12).
                        wv.connect_event(|_w, event| {
                            if event.event_type() == EventType::TouchpadPinch {
                                Propagation::Stop
                            } else {
                                Propagation::Proceed
                            }
                        });
                    });
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_document,
            get_page_sizes,
            get_page_scene,
            get_media
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
