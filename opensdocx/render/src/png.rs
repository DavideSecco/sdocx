//! `SVG -> PNG` rasterization, via the same `resvg`/`tiny_skia` pair already
//! validated in this codebase (the now-unused `crates/sdocx-cli`'s
//! `svg_to_png`) — kept here instead so both the Tauri app and
//! `opensdocx-cli` share the exact same function.

/// Rasterizes an SVG document string (as produced by [`crate::render_page_svg`])
/// to PNG bytes, at the SVG's own intrinsic size (no upscaling here — callers
/// that need a specific DPI should scale the SVG's `width`/`height` first).
pub fn svg_to_png(svg: &str) -> Result<Vec<u8>, String> {
    let mut opt = resvg::usvg::Options::default();
    // Load system fonts so any `<text>` element renders instead of being
    // silently dropped (text/tables aren't ported to this renderer yet, but
    // sticky-note labels already use `<text>`).
    opt.fontdb_mut().load_system_fonts();
    let tree = resvg::usvg::Tree::from_str(svg, &opt).map_err(|e| format!("invalid SVG: {e}"))?;
    let size = tree.size().to_int_size();
    let (w, h) = (size.width(), size.height());
    let mut pixmap =
        resvg::tiny_skia::Pixmap::new(w, h).ok_or_else(|| "failed to allocate pixmap".to_string())?;
    let mut pm = pixmap.as_mut();
    resvg::render(&tree, resvg::tiny_skia::Transform::identity(), &mut pm);
    pixmap.encode_png().map_err(|e| format!("PNG encode failed: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn svg_to_png_produces_valid_png_with_expected_size() {
        let svg = r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10" width="20" height="10"><rect x="0" y="0" width="20" height="10" fill="#252525"/></svg>"##;
        let png = svg_to_png(svg).expect("render should succeed");
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!((w, h), (20, 10));
    }
}
