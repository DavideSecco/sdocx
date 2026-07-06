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
    doc: Mutex<Option<sdocx::Document>>,
}

#[derive(Serialize)]
struct PageMeta {
    width: u32,
    height: u32,
    stroke_count: usize,
    element_count: usize,
}

#[derive(Serialize)]
struct DocMeta {
    page_count: usize,
    dark_mode: bool,
    background: Option<[u8; 3]>,
    pages: Vec<PageMeta>,
}

#[derive(Serialize)]
struct SceneStroke {
    points: Vec<[f64; 2]>,
    pressures: Vec<f64>,
    color: Option<[u8; 3]>,
    width: f32,
    tapered: bool,
    tool_id: Option<u8>,
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

#[derive(Serialize)]
struct SceneTemplate {
    id: u32,
    kind: String,
}

#[derive(Serialize)]
struct PageScene {
    width: u32,
    height: u32,
    background: Option<[u8; 3]>,
    template: Option<SceneTemplate>,
    strokes: Vec<SceneStroke>,
    images: Vec<SceneImage>,
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

impl DocMeta {
    fn build(doc: &sdocx::Document) -> Self {
        let pages = doc
            .pages
            .iter()
            .map(|p| PageMeta {
                width: p.width,
                height: p.height,
                stroke_count: p.strokes.len(),
                element_count: p.elements.len(),
            })
            .collect();
        DocMeta {
            page_count: doc.pages.len(),
            dark_mode: doc.metadata.dark_mode_compatibility.unwrap_or(false),
            background: doc.metadata.background_color.as_ref().map(color_arr),
            pages,
        }
    }
}

fn build_page_scene(page: &sdocx::Page) -> PageScene {
    let strokes = page
        .strokes
        .iter()
        .map(|s| SceneStroke {
            points: s.points.iter().map(|p| [p.x, p.y]).collect(),
            pressures: s.pressures.clone(),
            color: s.color.as_ref().map(color_arr),
            width: s.pen_width,
            tapered: s.tapered,
            tool_id: s.tool_id,
        })
        .collect();

    let mut images = Vec::new();
    let mut texts = Vec::new();
    for el in &page.elements {
        match el {
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

    let template = page.template.map(|t| SceneTemplate {
        id: t.id,
        kind: match t.source {
            sdocx::PageTemplateSource::BuiltIn => "builtin".into(),
            sdocx::PageTemplateSource::CustomPdf { .. } => "pdf".into(),
        },
    });

    PageScene {
        width: page.width,
        height: page.height,
        background: page.background_color.as_ref().map(color_arr),
        template,
        strokes,
        images,
        texts,
    }
}

/// Parse a `.sdocx` from a path, cache it in state, and return page metadata.
#[tauri::command]
fn open_document(path: String, state: State<AppState>) -> Result<DocMeta, String> {
    let doc = sdocx::parse(&path).map_err(|e| e.to_string())?;
    let meta = DocMeta::build(&doc);
    *state.doc.lock().unwrap() = Some(doc);
    Ok(meta)
}

/// Return the lightweight render scene for one page of the loaded document.
#[tauri::command]
fn get_page_scene(index: usize, state: State<AppState>) -> Result<PageScene, String> {
    let guard = state.doc.lock().unwrap();
    let doc = guard.as_ref().ok_or("no document loaded")?;
    let page = doc.pages.get(index).ok_or("page index out of range")?;
    Ok(build_page_scene(page))
}

/// Return one embedded media asset as a base64 blob (for images/audio).
#[tauri::command]
fn get_media(index: usize, state: State<AppState>) -> Result<MediaOut, String> {
    let guard = state.doc.lock().unwrap();
    let doc = guard.as_ref().ok_or("no document loaded")?;
    let asset = doc
        .metadata
        .media_assets
        .get(index)
        .ok_or("media index out of range")?;
    Ok(MediaOut {
        mime: asset.mime_type.clone(),
        base64: base64::engine::general_purpose::STANDARD.encode(&asset.data),
    })
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
            get_page_scene,
            get_media
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
