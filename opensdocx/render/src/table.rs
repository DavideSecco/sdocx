//! `SceneTable -> SVG`: direct port of `render.worker.ts`'s table drawing
//! block (cell fills → outer frame → inner grid → boundary edges → cell
//! text) — see that file's `renderJob` tables loop. No wrap logic needed:
//! `SceneTableCell` already carries a resolved single-line string and final
//! shrink-to-fit font size; only the underline/strike decoration extent
//! needs glyph-metrics measurement (`crate::font`), same as `crate::text`.

use crate::font::{self, FontStyle};
use crate::svg::{css, ink_for, n, xml_escape};
use crate::{PageScene, SceneTable, SceneTableCell};
use std::fmt::Write as _;

fn draw_one_table(out: &mut String, tb: &SceneTable, paper: [u8; 3], default_ink: [u8; 3]) {
    let xs = &tb.x_edges;
    let ys = &tb.y_edges;
    if xs.len() < 2 || ys.len() < 2 {
        return;
    }
    let (x0, x1) = (xs[0], xs[xs.len() - 1]);
    let (y0, y1) = (ys[0], ys[ys.len() - 1]);

    // Cell background fills sit beneath the borders. X is never flipped
    // (columns run left-to-right); Y is min/abs'd because a table with
    // geometry-edited rows can carry a flipped y_edges pair (the project's
    // documented "stacked-Y quirk" — not defensively "fixed" here, mirrored
    // byte-for-byte from the worker).
    for cell in &tb.cells {
        let Some(fill) = cell.fill else { continue };
        if cell.col + 1 >= xs.len() || cell.row + 1 >= ys.len() {
            continue;
        }
        let (fx0, fx1) = (xs[cell.col], xs[cell.col + 1]);
        let (fy0, fy1) = (ys[cell.row], ys[cell.row + 1]);
        let _ = write!(
            out,
            r#"<rect x="{}" y="{}" width="{}" height="{}" fill="{}"/>"#,
            n(fx0),
            n(fy0.min(fy1)),
            n(fx1 - fx0),
            n((fy1 - fy0).abs()),
            css(fill)
        );
    }

    let outer_col = css(tb.outer.color);
    let inner_col = css(tb.inner.color);
    let lw = n(tb.line_width);

    // A full rounded frame draws its own boundary; otherwise a boundary edge
    // is drawn if EITHER the outer frame OR the grid enables it (so "grid
    // horizontal only, no frame" still closes top+bottom). Interior lines
    // are grid-only.
    let rounded = tb.outer.has_v && tb.outer.has_h && tb.outer.radius > 0.0;
    if rounded {
        let _ = write!(
            out,
            r#"<rect x="{}" y="{}" width="{}" height="{}" rx="{}" ry="{}" fill="none" stroke="{outer_col}" stroke-width="{lw}"/>"#,
            n(x0),
            n(y0.min(y1)),
            n(x1 - x0),
            n((y1 - y0).abs()),
            n(tb.outer.radius),
            n(tb.outer.radius)
        );
    }

    // Interior grid lines (grid-only).
    let mut grid_d = String::new();
    if tb.inner.has_v {
        for &x in &xs[1..xs.len() - 1] {
            let _ = write!(grid_d, "M{} {}L{} {} ", n(x), n(y0), n(x), n(y1));
        }
    }
    if tb.inner.has_h {
        for &y in &ys[1..ys.len() - 1] {
            let _ = write!(grid_d, "M{} {}L{} {} ", n(x0), n(y), n(x1), n(y));
        }
    }
    if !grid_d.is_empty() {
        let _ = write!(
            out,
            r#"<path d="{}" stroke="{inner_col}" stroke-width="{lw}" fill="none"/>"#,
            grid_d.trim_end()
        );
    }

    // Boundary edges (top/bottom, left/right), unless the rounded frame
    // already drew them.
    if !rounded {
        if tb.outer.has_h || tb.inner.has_h {
            let col = if tb.outer.has_h { &outer_col } else { &inner_col };
            let _ = write!(
                out,
                r#"<path d="M{} {}L{} {} M{} {}L{} {}" stroke="{col}" stroke-width="{lw}" fill="none"/>"#,
                n(x0),
                n(y0),
                n(x1),
                n(y0),
                n(x0),
                n(y1),
                n(x1),
                n(y1)
            );
        }
        if tb.outer.has_v || tb.inner.has_v {
            let col = if tb.outer.has_v { &outer_col } else { &inner_col };
            let _ = write!(
                out,
                r#"<path d="M{} {}L{} {} M{} {}L{} {}" stroke="{col}" stroke-width="{lw}" fill="none"/>"#,
                n(x0),
                n(y0),
                n(x0),
                n(y1),
                n(x1),
                n(y0),
                n(x1),
                n(y1)
            );
        }
    }

    for cell in &tb.cells {
        draw_cell_text(out, cell, paper, default_ink);
    }
}

fn draw_cell_text(out: &mut String, cell: &SceneTableCell, paper: [u8; 3], default_ink: [u8; 3]) {
    if cell.text.is_empty() {
        return;
    }
    let style = FontStyle::from_flags(cell.bold, cell.italic);
    let fg = ink_for(cell.color, paper, default_ink);
    let weight = if cell.bold { r#" font-weight="bold""# } else { "" };
    let style_attr = if cell.italic { r#" font-style="italic""# } else { "" };
    let _ = write!(
        out,
        r#"<text x="{}" y="{}" font-size="{}" font-family="{}" fill="{fg}" dominant-baseline="middle"{weight}{style_attr}>{}</text>"#,
        n(cell.x),
        n(cell.y),
        n(cell.font),
        font::FONT_FAMILY_NAME,
        xml_escape(&cell.text)
    );
    // Under/strike span the measured glyph width, not the whole cell.
    if cell.underline || cell.strikethrough {
        let w = font::measure(&cell.text, style, cell.font);
        let stroke_w = 1.0 * crate::MPL_PT_TO_PAGE_UNITS;
        if cell.underline {
            let y = cell.y + cell.font * 0.42;
            let _ = write!(
                out,
                r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{fg}" stroke-width="{}"/>"#,
                n(cell.x),
                n(y),
                n(cell.x + w),
                n(y),
                n(stroke_w)
            );
        }
        if cell.strikethrough {
            let _ = write!(
                out,
                r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{fg}" stroke-width="{}"/>"#,
                n(cell.x),
                n(cell.y),
                n(cell.x + w),
                n(cell.y),
                n(stroke_w)
            );
        }
    }
}

pub fn draw_tables(out: &mut String, scene: &PageScene) {
    for tb in &scene.tables {
        draw_one_table(out, tb, scene.paper, scene.default_ink);
    }
}
