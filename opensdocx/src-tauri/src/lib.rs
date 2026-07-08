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
