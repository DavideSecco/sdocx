//! `SceneText -> SVG`: direct structural port of `render.worker.ts`'s
//! `segFont`/`fitPrefix`/`wrapCut`/`layoutRichText`/`paginateLines`/
//! `drawRichText` (the rich-text draw path), swapping every
//! `canvas.measureText`/`fontBoundingBox*` call for `crate::font::measure`/
//! `crate::font::glyph_box_height`. See `crate::font` for why glyph metrics
//! come from a bundled font instead of the worker's OS `sans-serif`.

use crate::font::{self, FontStyle};
use crate::svg::{css, ink_for, n, xml_escape};
use crate::{PageScene, SceneAlign, SceneText, SceneTextSeg};
use std::fmt::Write as _;

// The document body's decoded Common margins are [16,10,16,10]. Samsung's
// exact typed-text transform is stored unit -> PDF *5/3 -> page unit *8/3,
// so each vertical margin occupies 10*40/9 page units (mirrors the worker's
// `TYPED_TEXT_VERTICAL_MARGIN`).
const TYPED_TEXT_VERTICAL_MARGIN: f64 = 10.0 * 40.0 / 9.0;
// Calibrated against `canvas` + the browser's OS `sans-serif` vs. a
// matplotlib/pysdocx reference — UNVERIFIED against the bundled DejaVu Sans.
// Carried over as-is per the round-2 export plan; re-tune by visual
// comparison against `Allsamsungnotes_260630_113259` (this project's own
// pagination testbed sample) before trusting it, do not assume it transfers.
const TYPED_TEXT_GLYPH_WIDTH_SCALE: f64 = 0.96;

fn style_for(bold: bool, italic: bool) -> FontStyle {
    FontStyle::from_flags(bold, italic)
}

fn measure_chars(text: &[char], style: FontStyle, font_size: f64, width_scale: f64) -> f64 {
    if text.is_empty() {
        return 0.0;
    }
    let s: String = text.iter().collect();
    font::measure(&s, style, font_size) * width_scale
}

/// Longest prefix of `text` whose measured width fits in `max` (binary
/// search, mirrors the worker's `fitPrefix` / pysdocx `_fit_segment_prefix`).
fn fit_prefix(text: &[char], style: FontStyle, font_size: f64, max: f64, width_scale: f64) -> usize {
    let (mut lo, mut hi, mut best) = (1usize, text.len(), 0usize);
    while lo <= hi {
        let mid = (lo + hi) / 2;
        if measure_chars(&text[..mid], style, font_size, width_scale) <= max {
            best = mid;
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    best
}

/// Split for wrapping: cut at the last whitespace at/before `fit_len` when
/// there is one, else hard-cut (mirrors the worker's `wrapCut` / pysdocx
/// `_wrap_cut`).
fn wrap_cut(text: &[char], fit_len: usize) -> (Vec<char>, Vec<char>) {
    if fit_len >= text.len() {
        return (text.to_vec(), Vec::new());
    }
    let mut cut = fit_len;
    if let Some(idx) = text[..=fit_len].iter().rposition(|&c| c == ' ' || c == '\t') {
        if idx > 0 {
            cut = idx + 1;
        }
    }
    let head: Vec<char> = text[..cut].to_vec();
    let mut tail: Vec<char> = text[cut..].to_vec();
    while matches!(tail.first(), Some(' ') | Some('\t')) {
        tail.remove(0);
    }
    if head.is_empty() && !text.is_empty() {
        return (vec![text[0]], text[1..].to_vec());
    }
    (head, tail)
}

/// One styled, positioned run ready to draw — the Rust analog of the
/// worker's `VisLine["pieces"][i]`. `width` is the exact measured width of
/// `text` (already `width_scale`-adjusted) computed once during layout, so
/// drawing never re-measures.
struct DrawPiece {
    text: String,
    x: f64,
    width: f64,
    font: f64,
    bold: bool,
    italic: bool,
    underline: bool,
    strike: bool,
    color: Option<[u8; 3]>,
    highlight: Option<[u8; 3]>,
}

/// One laid-out visual row (the worker's `VisLine`): `y` is the flow offset
/// from the block anchor, `advance` the source paragraph's row advance.
struct VisLine {
    y: f64,
    advance: f64,
    pieces: Vec<DrawPiece>,
}

/// Accumulates visual rows for one text block's wrap pass — bundles the
/// mutable state `layoutRichText`'s closures capture (`out`/`pieces`/`y`/
/// `rowY`) so the wrap loop below can flush a row from multiple call sites
/// without fighting the borrow checker over several separate `&mut` locals.
struct Flow {
    out: Vec<VisLine>,
    pieces: Vec<DrawPiece>,
    y: f64,
    row_y: f64,
}

impl Flow {
    fn flush(&mut self, advance: f64) {
        if !self.pieces.is_empty() {
            self.out.push(VisLine {
                y: self.row_y,
                advance,
                pieces: std::mem::take(&mut self.pieces),
            });
        } else {
            self.pieces.clear();
        }
    }
}

/// Flow a rich text block into positioned visual rows with measured
/// wrapping — direct port of the worker's `layoutRichText`. See that
/// function's own comment for the per-paragraph gap/indent/prefix/alignment
/// order, preserved here unchanged.
fn layout_rich_text(t: &SceneText) -> Vec<VisLine> {
    let mut flow = Flow { out: Vec::new(), pieces: Vec::new(), y: 0.0, row_y: 0.0 };
    let width_scale = if t.paginate.is_some() { TYPED_TEXT_GLYPH_WIDTH_SCALE } else { 1.0 };

    for line in &t.lines {
        flow.y += line.lead_gap;
        flow.row_y = flow.y;
        let x0_base = line.x_offset;
        let mut x0 = x0_base;
        let mut max_width = line.max_width;

        if let Some(prefix) = &line.prefix {
            let prefix_chars: Vec<char> = prefix.text.chars().collect();
            let prefix_text_w = measure_chars(&prefix_chars, FontStyle::Regular, prefix.font, width_scale);
            let prefix_w = prefix
                .body_indent
                .unwrap_or_else(|| f64::max(prefix_text_w + prefix.pt * 0.9, prefix.pt * 2.4));
            flow.pieces.push(DrawPiece {
                text: prefix.text.clone(),
                x: x0 + prefix.marker_indent.unwrap_or(0.0),
                width: prefix_text_w,
                font: prefix.font,
                bold: false,
                italic: false,
                underline: false,
                strike: false,
                color: prefix.color,
                highlight: None,
            });
            x0 += prefix_w;
            max_width = f64::max(max_width - prefix_w, t.min_width);
        }

        // A paragraph only centers/right-aligns when its plain text (measured
        // at the block's base font, not per-run sizes) already fits
        // `max_width` unwrapped — a wrapped paragraph stays left-flush.
        if let Some(align) = &line.align {
            if !line.segs.is_empty() {
                let joined: Vec<char> = line.segs.iter().flat_map(|s| s.text.chars()).collect();
                let line_width = measure_chars(&joined, FontStyle::Regular, t.base_font, width_scale);
                if line_width < max_width {
                    x0 += match align {
                        SceneAlign::Center => (max_width - line_width) / 2.0,
                        SceneAlign::Right => max_width - line_width,
                    };
                }
            }
        }

        let right_edge = x0 + max_width;
        let mut x = x0;
        for seg in &line.segs {
            let style = style_for(seg.bold, seg.italic);
            let mut rest: Vec<char> = seg.text.chars().collect();
            while !rest.is_empty() {
                let w = measure_chars(&rest, style, seg.font, width_scale);
                if x + w <= right_edge {
                    push_piece(&mut flow.pieces, seg, &rest, x, w);
                    x += w;
                    rest.clear();
                    continue;
                }
                let fit = fit_prefix(&rest, style, seg.font, right_edge - x, width_scale);
                if fit == 0 {
                    if x == x0 {
                        // Nothing fits even from the margin: emit one char to
                        // guarantee progress.
                        let ch = rest[0];
                        let cw = measure_chars(&[ch], style, seg.font, width_scale);
                        push_piece(&mut flow.pieces, seg, &[ch], x, cw);
                        // `x` is unconditionally reset to `x0` right below —
                        // no `x += cw` needed here (this row is flushed either way).
                        rest.remove(0);
                    }
                    flow.flush(line.advance);
                    flow.y += line.advance;
                    flow.row_y = flow.y;
                    x = x0;
                    continue;
                }
                // A styled segment that would split mid-word only because the
                // row is already partially filled moves to the next row whole.
                let splits_mid_word = fit < rest.len() && !rest[..fit].iter().any(|&c| c == ' ' || c == '\t');
                if x > x0 && splits_mid_word {
                    let whole_w = measure_chars(&rest, style, seg.font, width_scale);
                    if whole_w <= max_width {
                        flow.flush(line.advance);
                        flow.y += line.advance;
                        flow.row_y = flow.y;
                        x = x0;
                        continue;
                    }
                }
                let (head, tail) = wrap_cut(&rest, fit);
                if head.is_empty() {
                    flow.flush(line.advance);
                    flow.y += line.advance;
                    flow.row_y = flow.y;
                    x = x0;
                    continue;
                }
                let head_w = measure_chars(&head, style, seg.font, width_scale);
                push_piece(&mut flow.pieces, seg, &head, x, head_w);
                x += head_w;
                if !tail.is_empty() {
                    flow.flush(line.advance);
                    flow.y += line.advance;
                    flow.row_y = flow.y;
                    x = x0;
                }
                rest = tail;
            }
        }
        flow.flush(line.advance);
        flow.y += line.advance + line.trail_gap;
        flow.row_y = flow.y;
    }
    flow.out
}

fn push_piece(pieces: &mut Vec<DrawPiece>, seg: &SceneTextSeg, text: &[char], x: f64, width: f64) {
    pieces.push(DrawPiece {
        text: text.iter().collect(),
        x,
        width,
        font: seg.font,
        bold: seg.bold,
        italic: seg.italic,
        underline: seg.underline,
        strike: seg.strike,
        color: seg.color,
        highlight: seg.highlight,
    });
}

/// Split laid-out rows into page-height bands and keep only band `slot` —
/// direct port of the worker's `paginateLines`. A heading bumped to a new
/// page retains its preceding inter-line gap; uniform rows have a zero gap
/// and start directly at the block anchor.
fn paginate_lines(lines: Vec<VisLine>, slot: usize, band_height: f64) -> Vec<VisLine> {
    let content_height = band_height - 2.0 * TYPED_TEXT_VERTICAL_MARGIN;
    let mut bands: Vec<Vec<VisLine>> = Vec::new();
    let mut cur: Vec<VisLine> = Vec::new();
    let mut base = lines.first().map(|l| l.y).unwrap_or(0.0);
    let mut previous: Option<(f64, f64)> = None; // (y, advance)
    for ln in lines {
        let mut y_page = ln.y - base;
        if !cur.is_empty() && y_page + ln.advance > content_height {
            bands.push(std::mem::take(&mut cur));
            let lead_gap = previous.map(|(py, pa)| (ln.y - (py + pa)).max(0.0)).unwrap_or(0.0);
            base = ln.y - lead_gap;
            y_page = lead_gap;
        }
        previous = Some((ln.y, ln.advance));
        cur.push(VisLine { y: y_page, advance: ln.advance, pieces: ln.pieces });
    }
    if !cur.is_empty() {
        bands.push(cur);
    }
    bands.into_iter().nth(slot).unwrap_or_default()
}

fn draw_seg_piece(out: &mut String, p: &DrawPiece, y: f64, paper: [u8; 3], default_ink: [u8; 3], width_scale: f64) {
    let style = style_for(p.bold, p.italic);
    let h = {
        let hh = font::glyph_box_height(style, p.font);
        if hh.is_finite() && hh > 0.0 { hh } else { p.font * 1.2 }
    };
    if let Some(hl) = p.highlight {
        let _ = write!(
            out,
            r#"<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>"#,
            n(p.x), n(y), n(p.width), n(h), css(hl)
        );
    }
    let fg = ink_for(p.color, paper, default_ink);
    let weight = if p.bold { r#" font-weight="bold""# } else { "" };
    let style_attr = if p.italic { r#" font-style="italic""# } else { "" };
    let text = xml_escape(&p.text);
    if (width_scale - 1.0).abs() < 1e-9 {
        let _ = write!(
            out,
            r#"<text x="{}" y="{}" font-size="{}" font-family="{}" fill="{fg}" dominant-baseline="hanging"{weight}{style_attr}>{text}</text>"#,
            n(p.x), n(y), n(p.font), font::FONT_FAMILY_NAME
        );
    } else {
        // Mirrors the worker's horizontal-only `c.scale(widthScale, 1)` hack:
        // translate to the piece origin, scale x only, draw at the local origin.
        let _ = write!(
            out,
            r#"<text transform="translate({},{}) scale({},1)" x="0" y="0" font-size="{}" font-family="{}" fill="{fg}" dominant-baseline="hanging"{weight}{style_attr}>{text}</text>"#,
            n(p.x), n(y), n(width_scale), n(p.font), font::FONT_FAMILY_NAME
        );
    }
    if p.underline || p.strike {
        // pysdocx decoration lines are 1.3 matplotlib pt (bridge = 3.40).
        let stroke_w = 1.3 * crate::MPL_PT_TO_PAGE_UNITS;
        if p.underline {
            let _ = write!(
                out,
                r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{fg}" stroke-width="{}"/>"#,
                n(p.x), n(y + h), n(p.x + p.width), n(y + h), n(stroke_w)
            );
        }
        if p.strike {
            let _ = write!(
                out,
                r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{fg}" stroke-width="{}"/>"#,
                n(p.x), n(y + h / 2.0), n(p.x + p.width), n(y + h / 2.0), n(stroke_w)
            );
        }
    }
}

fn draw_one_text(out: &mut String, t: &SceneText, paper: [u8; 3], default_ink: [u8; 3]) {
    let rows_flat = layout_rich_text(t);
    let width_scale = if t.paginate.is_some() { TYPED_TEXT_GLYPH_WIDTH_SCALE } else { 1.0 };
    let rows = match &t.paginate {
        Some(p) => paginate_lines(rows_flat, p.slot, p.band_height),
        None => rows_flat,
    };
    if rows.is_empty() {
        return;
    }
    let transform = if t.angle_deg != 0.0 {
        format!(r#"translate({},{}) rotate({})"#, n(t.anchor[0]), n(t.anchor[1]), n(t.angle_deg))
    } else {
        format!(r#"translate({},{})"#, n(t.anchor[0]), n(t.anchor[1]))
    };
    let _ = write!(out, r#"<g transform="{transform}">"#);
    for row in &rows {
        for p in &row.pieces {
            draw_seg_piece(out, p, row.y, paper, default_ink, width_scale);
        }
    }
    out.push_str("</g>");
}

pub fn draw_texts(out: &mut String, scene: &PageScene) {
    for t in &scene.texts {
        draw_one_text(out, t, scene.paper, scene.default_ink);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ScenePaginate, ScenePrefix, SceneTextLine};

    fn seg(text: &str, font: f64) -> SceneTextSeg {
        SceneTextSeg {
            text: text.to_string(),
            font,
            bold: false,
            italic: false,
            underline: false,
            strike: false,
            color: None,
            highlight: None,
        }
    }

    fn line(segs: Vec<SceneTextSeg>, max_width: f64) -> SceneTextLine {
        SceneTextLine {
            advance: 40.0,
            lead_gap: 0.0,
            trail_gap: 0.0,
            x_offset: 0.0,
            max_width,
            align: None,
            prefix: None,
            segs,
        }
    }

    fn text_block(lines: Vec<SceneTextLine>) -> SceneText {
        SceneText {
            anchor: [0.0, 0.0],
            wrap_width: 400.0,
            angle_deg: 0.0,
            base_font: 20.0,
            min_width: 80.0,
            lines,
            paginate: None,
        }
    }

    #[test]
    fn layout_is_deterministic() {
        let t = text_block(vec![line(vec![seg("hello world this wraps", 20.0)], 100.0)]);
        let a = layout_rich_text(&t);
        let b = layout_rich_text(&t);
        assert_eq!(a.len(), b.len());
        for (ra, rb) in a.iter().zip(b.iter()) {
            assert_eq!(ra.pieces.len(), rb.pieces.len());
            for (pa, pb) in ra.pieces.iter().zip(rb.pieces.iter()) {
                assert_eq!(pa.text, pb.text);
                assert_eq!(pa.x, pb.x);
            }
        }
        // A wide word should actually force more than one visual row.
        assert!(a.len() > 1);
    }

    #[test]
    fn empty_line_produces_no_row() {
        let t = text_block(vec![line(vec![], 100.0)]);
        let rows = layout_rich_text(&t);
        assert!(rows.is_empty());
    }

    #[test]
    fn single_word_wider_than_wrap_width_still_progresses() {
        // "mmmmmmmmmmmmmmmmmmmm" at a large font in a tiny width: must not
        // infinite-loop, and must still emit at least one piece per row.
        let t = text_block(vec![line(vec![seg("mmmmmmmmmmmmmmmmmmmm", 40.0)], 5.0)]);
        let rows = layout_rich_text(&t);
        assert!(!rows.is_empty());
        for row in &rows {
            assert!(!row.pieces.is_empty());
        }
    }

    #[test]
    fn prefix_reserves_width_and_emits_its_own_piece() {
        let mut l = line(vec![seg("body text", 20.0)], 100.0);
        l.prefix = Some(ScenePrefix {
            text: "1. ".to_string(),
            font: 20.0,
            pt: 15.0,
            marker_indent: None,
            body_indent: None,
            color: None,
        });
        let t = text_block(vec![l]);
        let rows = layout_rich_text(&t);
        assert!(!rows.is_empty());
        assert_eq!(rows[0].pieces[0].text, "1. ");
    }

    #[test]
    fn pagination_keeps_only_requested_slot() {
        let mut l1 = line(vec![seg("row one", 20.0)], 400.0);
        l1.advance = 100.0;
        let mut l2 = line(vec![seg("row two", 20.0)], 400.0);
        l2.advance = 100.0;
        let mut t = text_block(vec![l1, l2]);
        t.paginate = Some(ScenePaginate { slot: 1, band_height: 150.0 });
        let mut out = String::new();
        draw_one_text(&mut out, &t, [255, 255, 255], [0, 0, 0]);
        // Only the second row's text should be present in this page's band.
        assert!(out.contains("row two"));
        assert!(!out.contains("row one"));
    }
}
