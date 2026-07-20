//! `SVG -> PNG` rasterization, via the same `resvg`/`tiny_skia` pair already
//! validated in this codebase (the now-unused `crates/sdocx-cli`'s
//! `svg_to_png`) — kept here instead so both the Tauri app and
//! `opensdocx-cli` share the exact same function.

/// Rasterizes an SVG document string (as produced by [`crate::render_page_svg`])
/// to PNG bytes, at the SVG's own intrinsic size (no upscaling here — callers
/// that need a specific DPI should scale the SVG's `width`/`height` first).
pub fn svg_to_png(svg: &str) -> Result<Vec<u8>, String> {
    let mut opt = resvg::usvg::Options::default();
    // Register the bundled font directly into the fontdb resvg rasterizes
    // against — this (not the SVG's own embedded `@font-face` block) is what
    // makes PNG output deterministic/machine-independent, since it doesn't
    // depend on usvg correctly parsing that block (see `crate::font`).
    crate::font::register_into(opt.fontdb_mut());
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

    /// Regression guard for a confirmed, counterintuitive fact (round-2
    /// export plan risk #4): `resvg`/`usvg` 0.47 does NOT parse the SVG's own
    /// embedded `@font-face` block — verified manually with a minimal
    /// isolated repro (valid vs. deliberately-corrupted base64 font data
    /// produced visibly different glyph shapes in a real headless Chromium
    /// sandboxed to exclude DejaVu Sans, proving @font-face genuinely works
    /// in an actual browser; the equivalent resvg-only render came back
    /// blank). This is exactly why `svg_to_png` registers the bundled font
    /// directly into its own `fontdb` (`crate::font::register_into`) instead
    /// of relying on the embedded block — this test protects that: if a
    /// future `resvg` upgrade or refactor ever drops that explicit
    /// registration, rasterizing with a bare `Options` (no system fonts, no
    /// `register_into`) must still come back BLANK, not silently start
    /// working (which would mask the moment it becomes safe to simplify).
    /// The embedded `@font-face` block's job is real browsers/viewers, not
    /// our own PNG path.
    #[test]
    fn resvg_ignores_embedded_font_face_block() {
        let mut no_media = |_: usize| -> Option<(String, Vec<u8>)> { None };
        let text_svg = crate::svg::render_page_svg(
            &crate::PageScene {
                width: 200,
                height: 60,
                paper: [255, 255, 255],
                default_ink: [0, 0, 0],
                template: None,
                strokes: vec![],
                images: vec![],
                shapes: vec![],
                texts: vec![crate::SceneText {
                    anchor: [10.0, 10.0],
                    wrap_width: 180.0,
                    angle_deg: 0.0,
                    base_font: 30.0,
                    min_width: 40.0,
                    lines: vec![crate::SceneTextLine {
                        advance: 40.0,
                        lead_gap: 0.0,
                        trail_gap: 0.0,
                        x_offset: 0.0,
                        max_width: 180.0,
                        align: None,
                        prefix: None,
                        segs: vec![crate::SceneTextSeg {
                            text: "MMMM".to_string(),
                            font: 30.0,
                            bold: false,
                            italic: false,
                            underline: false,
                            strike: false,
                            color: Some([0, 0, 0]),
                            highlight: None,
                        }],
                    }],
                    paginate: None,
                }],
                sticky_notes: vec![],
                tables: vec![],
            },
            &mut no_media,
        );
        assert!(text_svg.contains("@font-face"), "expected an embedded font-face block");

        // Bare Options: no `load_system_fonts`, no `crate::font::register_into`.
        let opt = resvg::usvg::Options::default();
        let tree = resvg::usvg::Tree::from_str(&text_svg, &opt).expect("valid SVG");
        let size = tree.size().to_int_size();
        let mut pixmap = resvg::tiny_skia::Pixmap::new(size.width(), size.height()).unwrap();
        resvg::render(&tree, resvg::tiny_skia::Transform::identity(), &mut pixmap.as_mut());

        let has_ink = pixmap
            .pixels()
            .iter()
            .any(|p| p.red() != 255 || p.green() != 255 || p.blue() != 255);
        assert!(
            !has_ink,
            "resvg rendered glyphs from the embedded @font-face with no fonts \
             registered — if resvg has started supporting this, the doc comment \
             above (and svg.rs's font_face_block) should be updated to say so"
        );
    }
}
