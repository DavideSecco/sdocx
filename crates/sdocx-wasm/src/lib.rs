use serde::Serialize;
use wasm_bindgen::prelude::*;

/// Parse a `.sdocx` file from bytes.
///
/// Accepts a `Uint8Array` and returns a `Document` object.
#[wasm_bindgen]
pub fn parse(bytes: &[u8]) -> Result<JsValue, JsError> {
    let doc = sdocx::parse_bytes(bytes).map_err(|e| JsError::new(&e.to_string()))?;
    serde_wasm_bindgen::to_value(&doc).map_err(|e| JsError::new(&e.to_string()))
}

#[derive(Serialize)]
struct RenderedPage {
    width: u32,
    height: u32,
    svg: String,
}

#[derive(Serialize)]
struct RenderedDocument {
    pages: Vec<RenderedPage>,
}

/// Parse and render a `.sdocx` file from bytes to SVG.
///
/// Accepts a `Uint8Array` and returns `{ pages: [{ width, height, svg }] }`,
/// one entry per page. The SVG is produced by the same renderer as the CLI.
#[wasm_bindgen]
pub fn render(bytes: &[u8]) -> Result<JsValue, JsError> {
    let doc = sdocx::parse_bytes(bytes).map_err(|e| JsError::new(&e.to_string()))?;
    let pages = sdocx_render::render_document(&doc)
        .into_iter()
        .map(|p| RenderedPage {
            width: p.width,
            height: p.height,
            svg: p.svg,
        })
        .collect();
    let rendered = RenderedDocument { pages };
    serde_wasm_bindgen::to_value(&rendered).map_err(|e| JsError::new(&e.to_string()))
}
