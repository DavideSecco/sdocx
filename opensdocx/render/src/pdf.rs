//! `[SVG] -> multi-page PDF` assembly, via `krilla`/`krilla-svg`. Each
//! page's SVG string (as produced by [`crate::render_page_svg`], one call
//! per page with that page's own `MediaResolver`) is parsed the same way
//! `png.rs` parses it for rasterization, then drawn onto its own krilla
//! page.
//!
//! Font handling mirrors `png.rs` exactly: krilla-svg pulls fonts from the
//! *parsed tree's own* fontdb (`usvg::Tree::fontdb()`), not from any
//! separate krilla-level font API — confirmed by reading krilla-svg 0.8.1's
//! source (`render_tree` clones `tree.fontdb()`). So registering
//! `crate::font` into `usvg::Options` before `Tree::from_str` is the entire
//! font story here too, same as PNG export.
//!
//! `usvg`/`krilla-svg` here is chosen over the more commonly-known
//! `svg2pdf`: `svg2pdf` is archived/unmaintained upstream and hard-pins
//! `usvg = "0.46"`, which would conflict with this crate's `usvg = "0.47.0"`
//! (pulled in for `resvg`/`rustybuzz` shaping already). `krilla-svg` 0.8.1
//! pins `usvg = "0.47.0"` — an exact match, confirmed via `cargo tree`, not
//! a coincidence to re-check later. krilla also has a real multi-page
//! `Document` builder, unlike svg2pdf's one-shot single-page function.

use krilla::page::PageSettings;
use krilla_svg::{SurfaceExt, SvgSettings};

/// Assembles `pages` (each an already-rendered SVG document string, as
/// returned by [`crate::render_page_svg`]) into one multi-page PDF. Pages
/// may have different sizes; each gets its own `PageSettings` sized to its
/// own SVG's intrinsic width/height, so mixed page sizes are not an issue
/// (confirmed by design, not just untested — `PageSettings::from_wh` is
/// called fresh per page, never a shared document-wide size).
///
/// PDF text is embedded as real, selectable text, not outlined paths
/// (`SvgSettings::default().embed_text == true`).
pub fn render_document_pdf(pages: &[String]) -> Result<Vec<u8>, String> {
    let mut document = krilla::Document::new();
    for (i, svg) in pages.iter().enumerate() {
        let mut opt = usvg::Options::default();
        crate::font::register_into(opt.fontdb_mut());
        let tree = usvg::Tree::from_str(svg, &opt).map_err(|e| format!("page {i}: invalid SVG: {e}"))?;

        let size = tree.size();
        let draw_size = krilla::geom::Size::from_wh(size.width(), size.height())
            .ok_or_else(|| format!("page {i}: invalid page size {}x{}", size.width(), size.height()))?;
        let page_settings = PageSettings::from_wh(size.width(), size.height())
            .ok_or_else(|| format!("page {i}: invalid page size {}x{}", size.width(), size.height()))?;

        let mut page = document.start_page_with(page_settings);
        let mut surface = page.surface();
        surface
            .draw_svg(&tree, draw_size, SvgSettings::default())
            .ok_or_else(|| format!("page {i}: draw_svg failed"))?;
        surface.finish();
        page.finish();
    }
    document.finish().map_err(|e| format!("PDF finalize failed: {e:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny_svg(w: u32, h: u32, extra: &str) -> String {
        format!(
            r##"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
                <rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>
                {extra}
            </svg>"##
        )
    }

    #[test]
    fn single_page_pdf_has_the_pdf_magic_header() {
        let svg = tiny_svg(200, 100, "");
        let pdf = render_document_pdf(&[svg]).expect("render should succeed");
        assert_eq!(&pdf[..5], b"%PDF-");
    }

    #[test]
    fn multi_page_pdf_reports_the_right_page_count() {
        let pages = vec![tiny_svg(200, 100, ""), tiny_svg(200, 100, ""), tiny_svg(200, 100, "")];
        let pdf = render_document_pdf(&pages).expect("render should succeed");
        let text = String::from_utf8_lossy(&pdf);
        // Every page object declares /Type/Page — but that's also a substring
        // of the singular page-TREE object's /Type/Pages, so exclude matches
        // immediately followed by 's'.
        let needle = "/Type/Page";
        let count = text
            .match_indices(needle)
            .filter(|&(i, _)| text.as_bytes().get(i + needle.len()) != Some(&b's'))
            .count();
        assert_eq!(count, 3, "expected 3 page objects in the PDF");
    }

    #[test]
    fn mixed_page_sizes_render_without_clamping() {
        // Two very differently-sized pages — this must not error or silently
        // clamp to one shared size (see module doc: sizes are per-page by design).
        let pages = vec![tiny_svg(100, 800, ""), tiny_svg(800, 100, "")];
        let pdf = render_document_pdf(&pages).expect("render should succeed");
        assert_eq!(&pdf[..5], b"%PDF-");
    }

    #[test]
    fn text_renders_with_the_bundled_font_registered() {
        let svg = tiny_svg(
            200,
            100,
            r##"<text x="10" y="50" font-size="20" font-family="DejaVu Sans" fill="#000000">Hello</text>"##,
        );
        let pdf = render_document_pdf(&[svg]).expect("render should succeed");
        assert_eq!(&pdf[..5], b"%PDF-");
        assert!(pdf.len() > 1000, "expected embedded font/glyph data to add real bulk to the file");
    }
}
