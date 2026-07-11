//! SVG rendering for parsed `.sdocx` documents.
//!
//! This crate turns the data structures produced by [`sdocx`] into SVG strings.
//! It is the single source of truth for rendering, shared by the CLI (which also
//! rasterizes the SVG to PNG) and the WASM bindings (which hand the SVG to the
//! browser). Stroke pressure, rich text, embedded images, and dark-mode
//! background handling are all reproduced here.

use base64::Engine as _;
use sdocx::{Color, Document, MediaAsset, Page, PageElement, RichTextBox, RichTextRun, Stroke};
use std::fmt::Write as FmtWrite;

// Default ink for uncolored strokes, by canvas: light on dark, dark on light.
const DEFAULT_INK_DARK_MODE: &str = "#ffffff";
const DEFAULT_INK_LIGHT_MODE: &str = "#1a1a1a";
// Fallback canvas when a note carries no background color, matched to the ink.
const FALLBACK_BG_DARK_MODE: &str = "#252525";
const FALLBACK_BG_LIGHT_MODE: &str = "#fcfcfc";
// Pressure channel on v4.4.x files can be present but all-zero; treat as absent.
const PRESSURE_PRESENT_EPSILON: f64 = 0.01;

/// A single rendered page: its pixel dimensions and the SVG markup.
#[derive(Debug, Clone)]
pub struct RenderedPage {
    /// Page width in pixels.
    pub width: u32,
    /// Page height in pixels.
    pub height: u32,
    /// The SVG document for this page.
    pub svg: String,
}

/// Render every page of a document to SVG.
///
/// Dark-mode handling, the document background color, and embedded media assets
/// are all sourced from the document metadata, mirroring the CLI behavior.
///
/// Pages with no strokes and no elements are skipped: Samsung Notes archives can
/// carry a trailing blank page that the user never authored, and rendering it
/// would show a phantom empty page.
pub fn render_document(doc: &Document) -> Vec<RenderedPage> {
    let dark_mode = doc.metadata.dark_mode_compatibility.unwrap_or(false);
    doc.pages
        .iter()
        .filter(|page| !(page.strokes.is_empty() && page.elements.is_empty()))
        .map(|page| RenderedPage {
            width: page.width,
            height: page.height,
            svg: page_to_svg(
                page,
                doc.metadata.background_color.as_ref(),
                &doc.metadata.media_assets,
                dark_mode,
            ),
        })
        .collect()
}

fn color_hex(c: &Color) -> String {
    format!("#{:02x}{:02x}{:02x}", c.r, c.g, c.b)
}

/// Render a single page to an SVG document.
///
/// `fallback_bg` is the document-level background color, used when the page has
/// none (and, in dark mode, preferred over a light page template).
pub fn page_to_svg(
    page: &Page,
    fallback_bg: Option<&Color>,
    media_assets: &[MediaAsset],
    dark_mode: bool,
) -> String {
    // Dark-mode notes have light ink, so prefer the document's dark background
    // over the light page template; otherwise keep the template background.
    let bg_color = if dark_mode {
        fallback_bg.or(page.background_color.as_ref())
    } else {
        page.background_color.as_ref().or(fallback_bg)
    };
    let bg = bg_color.map(color_hex).unwrap_or_else(|| {
        if dark_mode {
            FALLBACK_BG_DARK_MODE
        } else {
            FALLBACK_BG_LIGHT_MODE
        }
        .into()
    });
    let vb_x = 0.0;
    let vb_y = 0.0;
    let vb_w = page.width as f64;
    let vb_h = page.height as f64;
    let svg_w = page.width;
    let svg_h = page.height;

    let mut svg = String::with_capacity(page.strokes.len() * 256);

    writeln!(
        svg,
        r#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_x:.1} {vb_y:.1} {vb_w:.1} {vb_h:.1}" width="{svg_w}" height="{svg_h}">"#,
    )
    .unwrap();

    writeln!(
        svg,
        r#"  <rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="{bg}"/>"#,
    )
    .unwrap();

    let default_ink = if dark_mode {
        DEFAULT_INK_DARK_MODE
    } else {
        DEFAULT_INK_LIGHT_MODE
    };
    for stroke in &page.strokes {
        render_stroke(&mut svg, stroke, default_ink);
    }
    for element in &page.elements {
        render_element(&mut svg, element, page, media_assets);
    }

    svg.push_str("</svg>\n");
    svg
}

fn render_element(
    svg: &mut String,
    element: &PageElement,
    page: &Page,
    media_assets: &[MediaAsset],
) {
    match element {
        PageElement::Image { bbox, media_index } => {
            // media_index is the decoded `<index>@` archive index (the parser's one
            // media currency, same as pysdocx) — resolve it against each asset's
            // own archive index, not its position in the list.
            let Some(asset) = media_assets
                .iter()
                .find(|a| a.archive_index() == Some(*media_index as u32))
            else {
                return;
            };
            let encoded = base64::engine::general_purpose::STANDARD.encode(&asset.data);
            writeln!(
                svg,
                r#"  <image x="{:.2}" y="{:.2}" width="{:.2}" height="{:.2}" href="data:{};base64,{}" preserveAspectRatio="none"/>"#,
                bbox.x_min,
                bbox.y_min,
                bbox.x_max - bbox.x_min,
                bbox.y_max - bbox.y_min,
                asset.mime_type,
                encoded,
            )
            .unwrap();
        }
        PageElement::TextBox(text_box) => render_text_box(svg, text_box, page),
        // Shapes/sticky notes are decoded by the parser but this SVG renderer
        // doesn't draw them yet — OpenSdocx's Scene renderer does (the SVG path
        // lags by design).
        PageElement::Shape(_) | PageElement::StickyNote { .. } => {}
    }
}

fn render_text_box(svg: &mut String, text_box: &RichTextBox, page: &Page) {
    let text = text_box.text.trim_end_matches('\n');
    if text.trim().is_empty() {
        return;
    }

    let is_note_body =
        text_box.bbox.x_max <= text_box.bbox.x_min || text_box.bbox.y_max <= text_box.bbox.y_min;
    let (x, y, width, height) = if is_note_body {
        (50.0, 0.0, page.width as f64 - 100.0, page.height as f64)
    } else {
        (
            text_box.bbox.x_min,
            text_box.bbox.y_min,
            text_box.bbox.x_max - text_box.bbox.x_min,
            text_box.bbox.y_max - text_box.bbox.y_min,
        )
    };
    let color = text_box
        .color
        .as_ref()
        .map(color_hex)
        .unwrap_or_else(|| "#252525".into());
    let font_size = text_box.font_size.map(samsung_font_to_svg).unwrap_or(37.0);
    let line_height = font_size * 1.35;
    let mut transform = String::new();
    if let Some(rotation) = text_box.rotation_degrees {
        let cx = x + width / 2.0;
        let cy = y + height / 2.0;
        transform = format!(r#" transform="rotate({rotation:.2} {cx:.2} {cy:.2})""#);
    }

    writeln!(svg, r#"  <g{transform}>"#).unwrap();
    if let Some(highlight) = text_box.highlight_color.as_ref() {
        writeln!(
            svg,
            r#"    <rect x="{x:.2}" y="{y:.2}" width="{width:.2}" height="{height:.2}" fill="{}"/>"#,
            color_hex(highlight),
        )
        .unwrap();
    }
    for (line_idx, line) in text.lines().enumerate() {
        if line.is_empty() {
            continue;
        }
        let text_y = y + font_size + line_idx as f64 * line_height;
        let decoration = if text_box.underline {
            r#" text-decoration="underline""#
        } else {
            ""
        };
        let line_start = text
            .lines()
            .take(line_idx)
            .map(|line| line.chars().count() + 1)
            .sum::<usize>();
        let spans = styled_line_spans(line, line_start, &text_box.runs);
        write!(
            svg,
            r#"    <text x="{x:.2}" y="{text_y:.2}" fill="{color}" font-family="Arial, sans-serif" font-size="{font_size:.2}"{decoration}>"#,
        )
        .unwrap();
        for span in spans {
            write!(
                svg,
                r#"<tspan{}{}>{}</tspan>"#,
                if span.bold {
                    r#" font-weight="bold""#
                } else {
                    ""
                },
                if span.italic {
                    r#" font-style="italic""#
                } else {
                    ""
                },
                escape_xml(span.text),
            )
            .unwrap();
        }
        svg.push_str("</text>\n");
    }
    svg.push_str("  </g>\n");
}

struct StyledSpan<'a> {
    text: &'a str,
    bold: bool,
    italic: bool,
}

fn styled_line_spans<'a>(
    line: &'a str,
    line_start: usize,
    runs: &[RichTextRun],
) -> Vec<StyledSpan<'a>> {
    let char_count = line.chars().count();
    let mut boundaries = vec![0, char_count];
    for run in runs {
        let start = run.start.saturating_sub(line_start).min(char_count);
        let end = run.end.saturating_sub(line_start).min(char_count);
        if start < end {
            boundaries.push(start);
            boundaries.push(end);
        }
    }
    boundaries.sort_unstable();
    boundaries.dedup();

    let byte_offsets = char_byte_offsets(line);
    let mut spans = Vec::new();
    for pair in boundaries.windows(2) {
        let start = pair[0];
        let end = pair[1];
        if start == end {
            continue;
        }
        let global_start = line_start + start;
        let global_end = line_start + end;
        let mut bold = false;
        let mut italic = false;
        for run in runs {
            if run.start < global_end && run.end > global_start {
                bold |= run.bold;
                italic |= run.italic;
            }
        }
        spans.push(StyledSpan {
            text: &line[byte_offsets[start]..byte_offsets[end]],
            bold,
            italic,
        });
    }
    spans
}

fn char_byte_offsets(text: &str) -> Vec<usize> {
    let mut offsets: Vec<usize> = text.char_indices().map(|(offset, _)| offset).collect();
    offsets.push(text.len());
    offsets
}

fn samsung_font_to_svg(size: f32) -> f64 {
    let size = size as f64;
    if size.is_finite() && size > 0.0 {
        (size * 2.18).clamp(8.0, 96.0)
    } else {
        37.0
    }
}

fn escape_xml(input: &str) -> String {
    input
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn render_stroke(svg: &mut String, stroke: &Stroke, default_ink: &str) {
    if stroke.points.len() < 2 {
        return;
    }

    let color = stroke
        .color
        .as_ref()
        .map(color_hex)
        .unwrap_or_else(|| default_ink.into());

    let base_width = normalized_stroke_width(stroke.pen_width);
    // Only ink-pen-category tools (stroke.tapered) have pressure-sensitive
    // width (a fountain/calligraphy nib effect) — highlighters/markers are
    // flat felt tips and render at a constant width regardless of pressure.
    let has_pressure = stroke.tapered
        && stroke.pressures.len() >= stroke.points.len() - 1
        && stroke
            .pressures
            .iter()
            .any(|&p| p > PRESSURE_PRESENT_EPSILON);

    if has_pressure {
        for j in 1..stroke.points.len() {
            let p_idx = (j - 1).min(stroke.pressures.len() - 1);
            let pressure = stroke.pressures[p_idx].max(0.05);
            let sw = base_width * (0.3 + 0.7 * pressure);

            let p1 = &stroke.points[j - 1];
            let p2 = &stroke.points[j];
            writeln!(
                svg,
                r#"  <line x1="{:.2}" y1="{:.2}" x2="{:.2}" y2="{:.2}" stroke="{color}" stroke-width="{sw:.2}" stroke-linecap="round"/>"#,
                p1.x, p1.y, p2.x, p2.y,
            )
            .unwrap();
        }
    } else {
        let pts_str: String = stroke
            .points
            .iter()
            .map(|p| format!("{:.2},{:.2}", p.x, p.y))
            .collect::<Vec<_>>()
            .join(" ");
        writeln!(
            svg,
            r#"  <polyline points="{pts_str}" fill="none" stroke="{color}" stroke-width="{base_width:.2}" stroke-linecap="round" stroke-linejoin="round"/>"#,
        )
        .unwrap();
    }
}

/// Normalize a raw Samsung pen width into a sensible SVG stroke width.
///
/// The upper bound (30.0) covers highlighters, which use much larger
/// pen_width values than ink pens (up to 57.37 seen so far, vs. 17.26 for
/// the widest pen tool) — a tighter clamp here was visibly flattening
/// highlighter strokes to a fraction of their real width.
pub fn normalized_stroke_width(pen_width: f32) -> f64 {
    let raw_width = pen_width as f64 / 2.5;
    if raw_width.is_finite() && raw_width > 0.0 {
        raw_width.clamp(0.4, 30.0)
    } else {
        1.0
    }
}

#[cfg(test)]
mod tests {
    use super::{normalized_stroke_width, page_to_svg, render_document};
    use sdocx::{BoundingBox, Color, Document, DocumentMetadata, Page, Point, Stroke};

    #[test]
    fn normalizes_invalid_stroke_widths() {
        assert_eq!(normalized_stroke_width(f32::NAN), 1.0);
        assert_eq!(normalized_stroke_width(f32::INFINITY), 1.0);
        assert_eq!(normalized_stroke_width(0.0), 1.0);
        assert_eq!(normalized_stroke_width(-1.0), 1.0);
    }

    #[test]
    fn clamps_extreme_stroke_widths() {
        assert_eq!(normalized_stroke_width(0.1), 0.4);
        assert_eq!(normalized_stroke_width(10_000.0), 30.0);
        assert_eq!(normalized_stroke_width(5.0), 2.0);
    }

    #[test]
    fn does_not_clamp_highlighter_widths() {
        // Widest highlighter width seen so far (size 100), confirmed on
        // samples/OnlyHighlighterBlack_*.sdocx — must not be flattened.
        let raw = 57.368_893_f32;
        assert!((normalized_stroke_width(raw) - 22.947557).abs() < 1e-4);
    }

    #[test]
    fn renders_empty_page_with_page_dimensions_and_background() {
        let page = Page {
            uuid: "page".into(),
            width: 1080,
            height: 1527,
            content_bbox: BoundingBox::default(),
            background_color: Some(Color {
                r: 0xcb,
                g: 0xda,
                b: 0xdd,
            }),
            template: None,
            strokes: Vec::new(),
            elements: Vec::new(),
        };

        let svg = page_to_svg(&page, None, &[], false);

        assert!(svg.contains(r#"viewBox="0.0 0.0 1080.0 1527.0""#));
        assert!(svg.contains(r#"width="1080" height="1527""#));
        assert!(svg.contains(r##"fill="#cbdadd""##));
    }

    #[test]
    fn render_document_skips_empty_pages() {
        let empty = Page {
            uuid: "blank".into(),
            width: 100,
            height: 100,
            content_bbox: BoundingBox::default(),
            background_color: None,
            template: None,
            strokes: Vec::new(),
            elements: Vec::new(),
        };
        let doc = Document {
            pages: vec![page_with_uncolored_stroke(), empty],
            metadata: DocumentMetadata::default(),
        };

        let rendered = render_document(&doc);
        assert_eq!(rendered.len(), 1, "trailing blank page must be skipped");
    }

    fn page_with_uncolored_stroke() -> Page {
        Page {
            uuid: "page".into(),
            width: 100,
            height: 100,
            content_bbox: BoundingBox::default(),
            background_color: None,
            template: None,
            strokes: vec![Stroke {
                bbox: BoundingBox::default(),
                points: vec![Point { x: 1.0, y: 1.0 }, Point { x: 9.0, y: 9.0 }],
                pressures: Vec::new(),
                timestamps: Vec::new(),
                tilt_x: Vec::new(),
                tilt_y: Vec::new(),
                color: None,
                pen_width: 2.0,
                tool_id: None,
                tapered: false,
            }],
            elements: Vec::new(),
        }
    }

    #[test]
    fn uncolored_stroke_defaults_to_dark_ink_in_light_mode() {
        let svg = page_to_svg(&page_with_uncolored_stroke(), None, &[], false);
        assert!(
            svg.contains(r##"stroke="#1a1a1a""##),
            "light-mode default ink"
        );
        assert!(!svg.contains(r##"stroke="#ffffff""##));
    }

    #[test]
    fn uncolored_stroke_defaults_to_light_ink_in_dark_mode() {
        let svg = page_to_svg(&page_with_uncolored_stroke(), None, &[], true);
        assert!(
            svg.contains(r##"stroke="#ffffff""##),
            "dark-mode default ink"
        );
        assert!(!svg.contains(r##"stroke="#1a1a1a""##));
    }

    #[test]
    fn missing_background_falls_back_to_mode_matched_canvas() {
        // No page or document background: the fallback canvas must match the ink
        // mode, or dark ink lands on a dark fallback (or vice versa) and vanishes.
        let light = page_to_svg(&page_with_uncolored_stroke(), None, &[], false);
        assert!(
            light.contains(r##"fill="#fcfcfc""##),
            "light-mode fallback bg"
        );
        let dark = page_to_svg(&page_with_uncolored_stroke(), None, &[], true);
        assert!(
            dark.contains(r##"fill="#252525""##),
            "dark-mode fallback bg"
        );
    }

    #[test]
    fn render_document_emits_one_svg_per_page_with_dimensions() {
        let doc = sdocx::parse("../../samples/handwritten.sdocx").expect("parse sample");
        assert!(!doc.pages.is_empty(), "sample has no pages");
        let rendered = render_document(&doc);
        assert_eq!(rendered.len(), doc.pages.len());
        for (page, r) in doc.pages.iter().zip(&rendered) {
            assert_eq!((r.width, r.height), (page.width, page.height));
            assert!(r.svg.starts_with("<svg"));
            assert!(r.svg.trim_end().ends_with("</svg>"));
        }
    }
}
