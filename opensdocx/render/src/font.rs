//! Bundled DejaVu Sans + real glyph-metrics measurement (`rustybuzz`), the
//! direct Rust equivalent of the worker's `canvas.measureText`/
//! `fontBoundingBoxAscent`/`fontBoundingBoxDescent`.
//!
//! Chosen (round-2 export plan, confirmed with the user) to make export
//! output deterministic and machine-independent — NOT to bit-match the
//! on-screen app's OS-dependent `sans-serif`, which this diverges from by
//! design (DejaVu renders wider than Arial/Helvetica). DejaVu specifically
//! (over e.g. Liberation Sans) because `pysdocx/render.py` renders with
//! matplotlib's default font, which IS DejaVu Sans, and several Scene-
//! builder heuristic constants (`build_scene_table`'s shrink-to-fit
//! `approx_width = chars*base_pt*7.0`, `MPL_PT_TO_PAGE_UNITS`, the typed-
//! text line-height ratios) were calibrated against that pysdocx/DejaVu
//! output vs. the Samsung ground truth — this minimizes drift from numbers
//! already tuned against real ground truth.
//!
//! Vendored fresh from the `ttf-dejavu` 2.37 release (Bitstream Vera +
//! DejaVu changes license, permissive for bundling — see
//! `assets/fonts/LICENSE`), not copied from any Python venv/node_modules.

use std::sync::OnceLock;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FontStyle {
    Regular,
    Bold,
    Italic,
    BoldItalic,
}

impl FontStyle {
    pub fn from_flags(bold: bool, italic: bool) -> Self {
        match (bold, italic) {
            (true, true) => FontStyle::BoldItalic,
            (true, false) => FontStyle::Bold,
            (false, true) => FontStyle::Italic,
            (false, false) => FontStyle::Regular,
        }
    }
}

/// Must match the family string DejaVu's own `name` table reports for all 4
/// styles (confirmed via `fc-list`) — SVG output selects sub-styles with
/// ordinary `font-weight`/`font-style` attributes against this one family,
/// relying on standard font-matching (the same mechanism `fontdb`/`resvg`
/// already use for the sticky-note label) to land on the right face.
pub const FONT_FAMILY_NAME: &str = "DejaVu Sans";

const REGULAR: &[u8] = include_bytes!("../assets/fonts/DejaVuSans.ttf");
const BOLD: &[u8] = include_bytes!("../assets/fonts/DejaVuSans-Bold.ttf");
const ITALIC: &[u8] = include_bytes!("../assets/fonts/DejaVuSans-Oblique.ttf");
const BOLD_ITALIC: &[u8] = include_bytes!("../assets/fonts/DejaVuSans-BoldOblique.ttf");

/// Raw bytes for `@font-face` embedding (SVG self-containment) — same 4
/// blobs the measurement faces below are parsed from.
pub fn bytes_for(style: FontStyle) -> &'static [u8] {
    match style {
        FontStyle::Regular => REGULAR,
        FontStyle::Bold => BOLD,
        FontStyle::Italic => ITALIC,
        FontStyle::BoldItalic => BOLD_ITALIC,
    }
}

struct Faces {
    regular: rustybuzz::Face<'static>,
    bold: rustybuzz::Face<'static>,
    italic: rustybuzz::Face<'static>,
    bold_italic: rustybuzz::Face<'static>,
}

// Parsed once per process, not per page/render call — `opensdocx-cli` can
// export many pages in one run, and re-parsing 4 TTFs per page would be
// wasted work.
static FACES: OnceLock<Faces> = OnceLock::new();

fn faces() -> &'static Faces {
    FACES.get_or_init(|| Faces {
        regular: rustybuzz::Face::from_slice(REGULAR, 0)
            .expect("bundled DejaVuSans.ttf is a valid font"),
        bold: rustybuzz::Face::from_slice(BOLD, 0)
            .expect("bundled DejaVuSans-Bold.ttf is a valid font"),
        italic: rustybuzz::Face::from_slice(ITALIC, 0)
            .expect("bundled DejaVuSans-Oblique.ttf is a valid font"),
        bold_italic: rustybuzz::Face::from_slice(BOLD_ITALIC, 0)
            .expect("bundled DejaVuSans-BoldOblique.ttf is a valid font"),
    })
}

fn face_for(style: FontStyle) -> &'static rustybuzz::Face<'static> {
    let f = faces();
    match style {
        FontStyle::Regular => &f.regular,
        FontStyle::Bold => &f.bold,
        FontStyle::Italic => &f.italic,
        FontStyle::BoldItalic => &f.bold_italic,
    }
}

/// Sum of shaped glyph advances for `text` at `font_size` (page units) — the
/// direct replacement for `canvas.measureText(text).width`.
pub fn measure(text: &str, style: FontStyle, font_size: f64) -> f64 {
    if text.is_empty() {
        return 0.0;
    }
    let face = face_for(style);
    let mut buffer = rustybuzz::UnicodeBuffer::new();
    buffer.push_str(text);
    let glyphs = rustybuzz::shape(face, &[], buffer);
    let total: i64 = glyphs
        .glyph_positions()
        .iter()
        .map(|p| p.x_advance as i64)
        .sum();
    total as f64 / face.units_per_em() as f64 * font_size
}

/// Ascent + descent at `font_size` (page units) — the analog of
/// `fontBoundingBoxAscent + fontBoundingBoxDescent`. NOT a confirmed
/// bit-identical metric match to canvas's font-bounding-box (unverified —
/// see the round-2 export plan's risk list); affects rich-text highlight-box
/// height and underline/strike placement, verify visually.
pub fn glyph_box_height(style: FontStyle, font_size: f64) -> f64 {
    let face = face_for(style);
    let units_per_em = face.units_per_em() as f64;
    let ascender = face.ascender() as f64;
    let descender = face.descender() as f64;
    (ascender - descender) / units_per_em * font_size
}

/// Registers the bundled font into `db` under `FONT_FAMILY_NAME`, and points
/// every generic CSS family keyword (`sans-serif` etc.) at it too, so any
/// leftover generic reference in the SVG (e.g. the sticky-note label)
/// resolves deterministically instead of depending on installed system
/// fonts. Used directly by `png.rs`'s rasterization `fontdb`, independent of
/// whether the SVG's own embedded `@font-face` block parses correctly.
pub fn register_into(db: &mut fontdb::Database) {
    for bytes in [REGULAR, BOLD, ITALIC, BOLD_ITALIC] {
        db.load_font_data(bytes.to_vec());
    }
    db.set_sans_serif_family(FONT_FAMILY_NAME);
    db.set_serif_family(FONT_FAMILY_NAME);
    db.set_cursive_family(FONT_FAMILY_NAME);
    db.set_fantasy_family(FONT_FAMILY_NAME);
    db.set_monospace_family(FONT_FAMILY_NAME);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn measure_is_positive_and_monotonic() {
        let a = measure("a", FontStyle::Regular, 20.0);
        let ab = measure("ab", FontStyle::Regular, 20.0);
        assert!(a > 0.0);
        assert!(ab > a);
    }

    #[test]
    fn measure_empty_is_zero() {
        assert_eq!(measure("", FontStyle::Regular, 20.0), 0.0);
    }

    #[test]
    fn measure_is_deterministic() {
        let a = measure("hello world", FontStyle::Bold, 17.3);
        let b = measure("hello world", FontStyle::Bold, 17.3);
        assert_eq!(a, b);
    }

    #[test]
    fn glyph_box_height_is_positive() {
        assert!(glyph_box_height(FontStyle::Regular, 20.0) > 0.0);
    }
}
