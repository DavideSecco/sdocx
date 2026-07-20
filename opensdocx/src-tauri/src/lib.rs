//! OpenSdocx — Tauri backend.
//!
//! Parses a `.sdocx` with the `sdocx` core and exposes a lightweight, UI-agnostic
//! per-page `Scene` to the frontend. The `Scene` model and the
//! `Document -> PageScene` builder live in the `opensdocx-render` crate (shared
//! with `opensdocx-cli`); this crate is a thin Tauri-command wrapper around it.

use std::sync::Mutex;

use base64::Engine as _;
use serde::Serialize;
use tauri::State;
use opensdocx_render::*;

/// The currently loaded document, kept in Tauri-managed state so the frontend can
/// request pages lazily without re-parsing.
#[derive(Default)]
struct AppState {
    reader: Mutex<Option<sdocx::Reader<std::fs::File>>>,
    typed_text_anchor: Mutex<Option<usize>>,
}

#[derive(Serialize)]
struct DocMeta {
    page_count: usize,
    dark_mode: bool,
    background: Option<[u8; 3]>,
    audio: Vec<AudioClip>,
}

/// One voice recording attached to the note, surfaced at document-load time so
/// the frontend can gate the toolbar audio button and build the clip list
/// without a round trip. `file_id` is the archive `<index>@` currency `get_media`
/// already resolves (images, PDF templates) — no dedicated audio-bytes command.
#[derive(Serialize)]
struct AudioClip {
    file_id: usize,
    name: String,
    duration_ms: i64,
    duration_str: String,
    created_time_us: i64,
}

#[derive(Serialize)]
struct MediaOut {
    mime: String,
    base64: String,
}

/// Open a `.sdocx` lazily (metadata + manifests only), cache the reader in state,
/// and return document metadata. Pages/media are decoded on demand below, so even
/// huge multi-page notes open instantly and cheaply.
#[tauri::command]
async fn open_document(path: String, state: State<'_, AppState>) -> Result<DocMeta, String> {
    let mut reader = sdocx::open(&path).map_err(|e| e.to_string())?;
    let typed_text_anchor = find_typed_text_anchor(&mut reader)?;
    let audio = reader
        .metadata()
        .note_voice_clips
        .iter()
        .map(|c| AudioClip {
            file_id: c.file_id as usize,
            name: c.name.clone(),
            duration_ms: c.duration_ms,
            duration_str: c.duration_str.clone(),
            created_time_us: c.created_time_us,
        })
        .collect();
    let meta = DocMeta {
        page_count: reader.page_count(),
        dark_mode: reader.metadata().dark_mode_compatibility.unwrap_or(false),
        background: reader.metadata().background_color.as_ref().map(color_arr),
        audio,
    };
    *state.reader.lock().unwrap() = Some(reader);
    *state.typed_text_anchor.lock().unwrap() = typed_text_anchor;
    Ok(meta)
}

/// Parse and return the lightweight render scene for a single page (on demand).
///
/// The Reader mutex is held only while extracting the page's bytes from the ZIP;
/// the parse itself runs outside the lock, so concurrent page requests (scroll,
/// prefetch) parse in parallel instead of queueing on one page at a time.
#[tauri::command]
async fn get_page_scene(index: usize, state: State<'_, AppState>) -> Result<PageScene, String> {
    let typed_text_anchor = *state.typed_text_anchor.lock().unwrap();
    let inputs = {
        let mut guard = state.reader.lock().unwrap();
        let reader = guard.as_mut().ok_or("no document loaded")?;
        gather_page_inputs(reader, typed_text_anchor, index)?
    };
    assemble_page_scene(inputs)
}

/// Render one page to SVG or PNG and write it to `path` (chosen by the
/// frontend via the save-file dialog). Builds the exact same `PageScene` as
/// `get_page_scene`, then calls the shared `opensdocx-render` draw functions
/// — the same ones `opensdocx-cli` calls — so the exported file and the
/// on-screen render come from one code path. Exports only the current page;
/// for the whole document as one file, see `export_document_pdf`.
#[tauri::command]
async fn export_page(
    index: usize,
    format: String,
    path: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let typed_text_anchor = *state.typed_text_anchor.lock().unwrap();
    let mut guard = state.reader.lock().unwrap();
    let reader = guard.as_mut().ok_or("no document loaded")?;
    let inputs = gather_page_inputs(reader, typed_text_anchor, index)?;
    let scene = assemble_page_scene(inputs)?;
    let mut media = |media_index: usize| -> Option<(String, Vec<u8>)> {
        let mime = reader.media_asset(media_index)?.mime_type.clone();
        let bytes = reader.media_bytes(media_index).ok()?;
        Some((mime, bytes))
    };
    let svg = opensdocx_render::render_page_svg(&scene, &mut media);
    match format.as_str() {
        "svg" => std::fs::write(&path, svg).map_err(|e| e.to_string()),
        "png" => {
            let png = opensdocx_render::svg_to_png(&svg)?;
            std::fs::write(&path, png).map_err(|e| e.to_string())
        }
        other => Err(format!("unsupported export format: {other}")),
    }
}

/// Render EVERY page into one multi-page PDF and write it to `path`. Unlike
/// `export_page` (current page only, SVG/PNG), PDF always exports the whole
/// document — a deliberate product difference (PDF's natural unit is a
/// multi-page document, not a single image). Holds the reader lock for the
/// whole loop: this is an explicit, one-shot user action (not a scroll-
/// driven hot path like `get_page_scene`), so a brief lock on concurrent
/// page requests during export is an accepted tradeoff, not an oversight —
/// same shape as `get_page_sizes` below.
#[tauri::command]
async fn export_document_pdf(path: String, state: State<'_, AppState>) -> Result<(), String> {
    let typed_text_anchor = *state.typed_text_anchor.lock().unwrap();
    let mut guard = state.reader.lock().unwrap();
    let reader = guard.as_mut().ok_or("no document loaded")?;
    let n = reader.page_count();
    let mut svgs = Vec::with_capacity(n);
    for index in 0..n {
        let inputs = gather_page_inputs(reader, typed_text_anchor, index)?;
        let scene = assemble_page_scene(inputs)?;
        let mut media = |media_index: usize| -> Option<(String, Vec<u8>)> {
            let mime = reader.media_asset(media_index)?.mime_type.clone();
            let bytes = reader.media_bytes(media_index).ok()?;
            Some((mime, bytes))
        };
        svgs.push(opensdocx_render::render_page_svg(&scene, &mut media));
    }
    let pdf = opensdocx_render::render_document_pdf(&svgs)?;
    std::fs::write(&path, pdf).map_err(|e| e.to_string())
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
/// `index` is the decoded `<index>@` archive index carried by the Scene
/// (images, PDF templates) — the Reader resolves it internally.
#[tauri::command]
async fn get_media(index: usize, state: State<'_, AppState>) -> Result<MediaOut, String> {
    let mut guard = state.reader.lock().unwrap();
    let reader = guard.as_mut().ok_or("no document loaded")?;
    let mime = reader
        .media_asset(index)
        .map(|a| a.mime_type.clone())
        .ok_or("unknown media archive index")?;
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

/// Read a custom-template image by the basename stored in its app-private URI.
/// Samsung prefixes embedded media members with `<index>@`, so compare only the
/// suffix after that prefix.
#[tauri::command]
async fn get_media_by_name(
    filename: String,
    state: State<'_, AppState>,
) -> Result<MediaOut, String> {
    let index = {
        let guard = state.reader.lock().unwrap();
        let reader = guard.as_ref().ok_or("no document loaded")?;
        reader
            .metadata()
            .media_assets
            .iter()
            .find(|asset| asset.name.rsplit('@').next() == Some(filename.as_str()))
            .and_then(|asset| asset.archive_index())
            .ok_or("custom template media not embedded")? as usize
    };
    get_media(index, state).await
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

    /// Document-level text is not intrinsically page-addressed. The benchmark
    /// puts its typed body on physical page 5; pin the same first-empty-page
    /// placement used by pysdocx so an app pagination change cannot silently
    /// overlay it on page 1 again.
    #[test]
    fn typed_text_anchor_matches_end_to_end_samples() {
        let cases = [
            ("Allsamsungnotes_260630_113259.sdocx", Some(4)),
            ("Associationpages&stickynote&images&audio_260701_183225.sdocx", Some(2)),
            ("Machine_learning_riassunto_Supervised_Learning_260208_110644.sdocx", None),
            ("Mathsolver&Hyperlink_260711_180442.sdocx", Some(1)),
            ("OnlyImages_260702_190147.sdocx", None),
            ("OnlyTextTypeWritten_260701_180427.sdocx", Some(0)),
            ("OnlyTextTypeWritten_squared_260703_013624.sdocx", Some(0)),
            ("OnlyTypeWrittenTextDifferentFont_260713_212408.sdocx", Some(0)),
            (
                "OnlytextTypewritten-Sistematic-carattere15_260713_212435.sdocx",
                Some(0),
            ),
            ("Tabella4x3Regolare_260711_160040.sdocx", None),
            ("Tabella4x3Regolarev2_260711_174656.sdocx", None),
            ("cs61bl_su22.sdocx", None),
            ("quiz.sdocx", None),
        ];
        for (name, expected) in cases {
            if let Some(mut reader) = sample(name) {
                let actual = find_typed_text_anchor(&mut reader).unwrap();
                assert_eq!(actual, expected, "{name}");
            }
        }
        if let Some(mut reader) = sample("OnlyShapesblack_new_260701_185935.sdocx") {
            assert_eq!(find_typed_text_anchor(&mut reader).unwrap(), None);
        }
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
            get_media,
            get_media_by_name,
            export_page,
            export_document_pdf
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
