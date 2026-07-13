// Rasterizes a page Scene to an ImageBitmap off the main thread, so scrolling and
// zooming never block on drawing. The main thread posts a Job; we reply with the
// finished ImageBitmap (a transferable) tagged with the same id.

type RGB = [number, number, number];
interface Stroke {
  points: [number, number][];
  color: RGB | null;
  width: number;
  tapered: boolean;
  /** Per-point pressure quantized 0..255; present only on tapered strokes. */
  pressures?: number[];
}
interface SImage { x: number; y: number; w: number; h: number; media_index: number }
// Rich text: layout (anchor/wrap/rotation/line advances) and styling come fully
// resolved from the Rust Scene builder; only glyph measurement — and thus the
// actual wrap points — happens here, since Rust has no font metrics.
interface STextSeg {
  text: string;
  font: number; // em size in page units
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  color: RGB | null;
  highlight: RGB | null;
}
// A paragraph's list/todo marker glyph — measured and reserved like a segment
// (pysdocx `_paragraph_prefix` + the prefix-emit block in `_render_rich_text`).
interface STextPrefix {
  text: string;
  font: number; // em size in page units, like STextSeg.font
  // The SAME size, unbridged (raw matplotlib points): pysdocx's own prefix-gap
  // formula (`prefix_text_w + prefix_pt*0.9`, floor `prefix_pt*2.4`) adds this
  // raw point number directly to a page-unit glyph-width measurement — a
  // pre-existing unit quirk in the reference renderer, kept byte-for-byte here
  // rather than "fixed" so the reserved gap matches pysdocx's spacing exactly.
  pt: number;
  color: RGB | null;
}
interface STextLine {
  // This paragraph's own row height, reused for every visual row it wraps
  // into (pysdocx `rendered_line_h` / `_blank_advance`).
  advance: number;
  // Extra gap added once before/after this paragraph's first/last visual row
  // (pysdocx `space_before`/`space_after * PARA_SPACE_UNIT`).
  lead_gap: number;
  trail_gap: number;
  // Indent offset added to the block anchor's x for every visual row of this
  // paragraph, page units (pysdocx `indent * 70`).
  x_offset: number;
  // This paragraph's own available width before its list-prefix (if any) is
  // subtracted (pysdocx `line_max_width`).
  max_width: number;
  // Undefined = left. Applied only when the paragraph's plain text already
  // fits `max_width` (after the prefix is subtracted) without wrapping — a
  // wrapped paragraph never centers/right-aligns in pysdocx either.
  align?: "center" | "right";
  prefix?: STextPrefix;
  segs: STextSeg[];
}
interface SText {
  anchor: [number, number];
  wrap_width: number;
  angle_deg: number;
  // This block's plain (non-bold/italic) font size, page units, like
  // STextSeg.font — used only to measure whether a paragraph's alignment
  // shift applies (pysdocx measures the alignment pre-check at this same
  // plain base size, not per-run sizes).
  base_font: number;
  // `base font (raw pt) * 4`, the wrap-width floor pysdocx applies after
  // subtracting a measured list-prefix width from a paragraph's max_width.
  min_width: number;
  lines: STextLine[];
  // Present only for the document-level typed note body: the flow is laid out in
  // full, then split into page-height bands; this page draws only band `slot`
  // (pysdocx paginate_typed_text / _paginate_segments).
  paginate?: { slot: number; band_height: number };
}
// Template style (kind + pitches/origin/color/line_width, and the PDF media/page link) comes
// fully resolved from the Rust Scene builder — no style constants here (single source,
// docs/app/README.md risk ②). kind: grid | line | dot | oxford | pdf | plain.
interface STemplate {
  id: number;
  kind: string;
  origin?: [number, number];
  color?: RGB;
  line_width?: number;
  row_spacing?: number;
  col_spacing?: number;
  dot_radius?: number;
  margin_x?: number;
  margin_color?: RGB;
  pdf_media_index?: number;
  pdf_page_index?: number;
}
// Shape geometry is resolved in the Scene builder too: ellipse/round_rect arrive as
// native-primitive params, arrows carry prebuilt head triangles.
interface SEllipse { cx: number; cy: number; rx: number; ry: number; rotation_deg: number }
interface SRoundRect { cx: number; cy: number; w: number; h: number; rotation_deg: number; radius: number }
// True vector outline (see opensdocx/src-tauri/src/lib.rs SceneOutlineOp): ported
// 1:1 from the file's own path ops, so a curve draws as a real bezierCurveTo instead
// of a flattened polyline — only heart/freeform-smooth shapes carry a "C" op.
interface SOutlineOp { op: "M" | "L" | "C"; p: [number, number]; c1?: [number, number]; c2?: [number, number] }
interface SShape {
  kind: string;
  points: [number, number][];
  color: RGB | null;
  width: number;
  closed: boolean;
  ellipse?: SEllipse;
  round_rect?: SRoundRect;
  outline?: SOutlineOp[];
  heads?: [number, number][][];
}
interface SSticky { x: number; y: number; w: number; h: number; media_index: number; bg_color: RGB | null }
// Table cells arrive fully resolved (position, shrink-to-fit font, style,
// background fill, under/strike segments) from the Scene builder; the worker
// only paints cell fills, strokes the grid, and fills the texts.
interface STableCell {
  col: number;
  row: number;
  x: number;
  y: number;
  text: string;
  font: number;
  bold: boolean;
  italic: boolean;
  color: RGB | null;
  fill?: RGB; // cell background (rect from col/row + x_edges/y_edges)
  underline?: boolean;
  strikethrough?: boolean;
}
interface STableBorder { color: RGB; has_v: boolean; has_h: boolean; radius: number }
interface STable {
  x_edges: number[];
  y_edges: number[];
  outer: STableBorder;
  inner: STableBorder;
  line_width: number;
  cells: STableCell[];
}
interface PageScene {
  width: number;
  height: number;
  paper: RGB;        // RE-decoded page paper color (fill)
  default_ink: RGB;  // paper-contrast ink, resolved in Rust
  template: STemplate | null;
  strokes: Stroke[];
  images: SImage[];
  shapes: SShape[];
  texts: SText[];
  sticky_notes: SSticky[];
  tables: STable[];
}
interface Job {
  id: number;
  scene: PageScene;
  scale: number; // device px per page unit
  images: { index: number; bitmap: ImageBitmap }[];
  /** Pre-rasterized PDF/custom-image template background from the main thread.
   * A structured clone of the cached bitmap — the worker owns it. */
  template_bitmap?: ImageBitmap;
}

function rgb(c: RGB | null, fb: string): string {
  return c ? `rgb(${c[0]},${c[1]},${c[2]})` : fb;
}
function css(c: RGB): string {
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
// Effective ink for a piece of content: its own color, unless that color is
// absent OR equal to the paper (the "default ink" indicator) — then the
// paper-contrast ink resolved in Rust (scene.default_ink). Mirrors pysdocx
// `if color is None or color == bg_color: color = default_ink`. Both `paper`
// and `di` come per-page from the Scene builder (single source), so the old
// document-level "dark mode" flag is gone.
function inkFor(c: RGB | null, paper: RGB, di: RGB): string {
  if (!c || (c[0] === paper[0] && c[1] === paper[1] && c[2] === paper[2])) return css(di);
  return css(c);
}

function drawShape(c: OffscreenCanvasRenderingContext2D, s: SShape): void {
  if (s.ellipse) {
    const e = s.ellipse;
    c.beginPath();
    c.ellipse(e.cx, e.cy, e.rx, e.ry, (e.rotation_deg * Math.PI) / 180, 0, Math.PI * 2);
    c.stroke();
  } else if (s.round_rect) {
    const r = s.round_rect;
    c.save();
    c.translate(r.cx, r.cy);
    c.rotate((r.rotation_deg * Math.PI) / 180);
    c.beginPath();
    c.roundRect(-r.w / 2, -r.h / 2, r.w, r.h, r.radius);
    c.stroke();
    c.restore();
  } else if (s.outline && s.outline.length > 0) {
    const path = new Path2D();
    for (const op of s.outline) {
      if (op.op === "M") path.moveTo(op.p[0], op.p[1]);
      else if (op.op === "L") path.lineTo(op.p[0], op.p[1]);
      else path.bezierCurveTo(op.c1![0], op.c1![1], op.c2![0], op.c2![1], op.p[0], op.p[1]);
    }
    if (s.closed) path.closePath();
    c.stroke(path);
  } else if (s.points.length >= 2) {
    const path = new Path2D();
    path.moveTo(s.points[0][0], s.points[0][1]);
    for (let i = 1; i < s.points.length; i++) path.lineTo(s.points[i][0], s.points[i][1]);
    if (s.closed) path.closePath();
    c.stroke(path);
  }
  for (const head of s.heads ?? []) {
    c.beginPath();
    c.moveTo(head[0][0], head[0][1]);
    c.lineTo(head[1][0], head[1][1]);
    c.lineTo(head[2][0], head[2][1]);
    c.closePath();
    c.fill();
  }
}

// One smooth Path2D over points[from..=to] (quadratic through segment midpoints).
function strokePath(points: [number, number][], from: number, to: number): Path2D {
  const path = new Path2D();
  path.moveTo(points[from][0], points[from][1]);
  if (to - from === 1) {
    path.lineTo(points[to][0], points[to][1]);
    return path;
  }
  for (let i = from + 1; i < to; i++) {
    const mx = (points[i][0] + points[i + 1][0]) / 2;
    const my = (points[i][1] + points[i + 1][1]) / 2;
    path.quadraticCurveTo(points[i][0], points[i][1], mx, my);
  }
  path.lineTo(points[to][0], points[to][1]);
  return path;
}

// Pressure-sensitive width for ink-pen strokes (matches pysdocx render.py):
// segment width = base * (0.3 + 0.7 * pressure), pressure of the segment's start
// point. Drawing each segment separately would be hundreds of stroke() calls, so
// consecutive segments whose width stays within a tolerance band are batched into
// one smooth sub-path; round caps make the seams invisible.
function drawTapered(c: OffscreenCanvasRenderingContext2D, s: Stroke, base: number): void {
  const pts = s.points;
  const press = s.pressures!;
  const widthAt = (k: number) => base * (0.3 + 0.7 * (press[k] ?? press[press.length - 1] ?? 128) / 255);
  const tol = Math.max(base * 0.12, 0.25);
  let from = 0;
  let groupW = widthAt(0);
  for (let k = 1; k < pts.length - 1; k++) {
    const w = widthAt(k);
    if (Math.abs(w - groupW) > tol) {
      c.lineWidth = groupW;
      c.stroke(strokePath(pts, from, k));
      from = k;
      groupW = w;
    }
  }
  c.lineWidth = groupW;
  c.stroke(strokePath(pts, from, pts.length - 1));
}

function segFont(seg: STextSeg): string {
  return `${seg.italic ? "italic " : ""}${seg.bold ? "bold " : ""}${seg.font}px sans-serif`;
}

// Longest prefix of `text` whose measured width fits in `max` (binary search,
// mirrors pysdocx _fit_segment_prefix).
function fitPrefix(c: OffscreenCanvasRenderingContext2D, text: string, max: number): number {
  let lo = 1, hi = text.length, best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (c.measureText(text.slice(0, mid)).width <= max) { best = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  return best;
}

// Split for wrapping: cut at the last whitespace at/before fitLen when there is
// one, else hard-cut (pysdocx _wrap_cut).
function wrapCut(text: string, fitLen: number): [string, string] {
  if (fitLen >= text.length) return [text, ""];
  let cut = fitLen;
  const ws = Math.max(text.lastIndexOf(" ", fitLen), text.lastIndexOf("\t", fitLen));
  if (ws > 0) cut = ws + 1;
  const head = text.slice(0, cut);
  const tail = text.slice(cut).replace(/^[ \t]+/, "");
  if (!head && text) return [text.slice(0, 1), text.slice(1)];
  return [head, tail];
}

// Draw one measured segment piece at (x, y): highlight box behind, glyphs, then
// underline/strikethrough decoration lines (pysdocx _draw_text_segment).
function drawSegPiece(
  c: OffscreenCanvasRenderingContext2D,
  seg: STextSeg,
  text: string,
  x: number,
  y: number,
  paper: RGB,
  di: RGB,
): number {
  c.font = segFont(seg);
  const m = c.measureText(text);
  const w = m.width;
  const asc = m.fontBoundingBoxAscent, desc = m.fontBoundingBoxDescent;
  const h = Number.isFinite(asc + desc) && asc + desc > 0 ? asc + desc : seg.font * 1.2;
  if (seg.highlight) {
    c.fillStyle = rgb(seg.highlight, "#ffff00");
    c.fillRect(x, y, w, h);
  }
  const fg = inkFor(seg.color, paper, di);
  c.fillStyle = fg;
  c.fillText(text, x, y);
  if (seg.underline || seg.strike) {
    c.strokeStyle = fg;
    // pysdocx decoration lines are 1.3 matplotlib pt (the Scene's pt→page-units
    // bridge is 3.40).
    c.lineWidth = 1.3 * 3.4;
    if (seg.underline) {
      c.beginPath();
      c.moveTo(x, y + h);
      c.lineTo(x + w, y + h);
      c.stroke();
    }
    if (seg.strike) {
      c.beginPath();
      c.moveTo(x, y + h / 2);
      c.lineTo(x + w, y + h / 2);
      c.stroke();
    }
  }
  return w;
}

// One laid-out visual row: `y` is the flow offset from the anchor, `advance` the
// source line's advance, `pieces` the styled runs to draw at their x within the row.
interface VisLine { y: number; advance: number; pieces: { seg: STextSeg; text: string; x: number }[] }

// pysdocx typed-note pagination constants (render.py TYPED_TEXT_Y0 / _paginate_segments
// default bottom_pad). The note body flows from the top margin y0 and a line whose
// bottom would cross `band_height - PAGE_PAD` is bumped whole to the next band.
const TYPED_TEXT_Y0 = 80;
const TYPED_TEXT_PAGE_PAD = 40;

// Flow a rich text block into positioned visual rows with measured wrapping
// (pysdocx _render_rich_text's segment loop, one source `line` per paragraph).
// Blank source lines advance `y` but emit no row — matching pysdocx, whose sink
// only records drawn segments, so pagination keys off real content rows only.
//
// Per paragraph: `lead_gap` shifts `y` down once before the first row (pysdocx
// `space_before`); indent/prefix/alignment resolve this paragraph's starting x
// and available width (pysdocx indent/`_paragraph_prefix`/align block, in that
// order — alignment must see the post-prefix width); the wrap loop below is
// otherwise unchanged; the closing `y += line.advance + line.trail_gap` folds
// in `space_after` once, after the paragraph's last visual row. Pagination's
// fit check (`paginateLines`) uses each pushed row's `advance` alone — not
// `trail_gap` — matching pysdocx `_paginate_segments`.
function layoutRichText(c: OffscreenCanvasRenderingContext2D, t: SText): VisLine[] {
  const out: VisLine[] = [];
  let y = 0;
  let rowY = 0;
  let pieces: VisLine["pieces"] = [];
  const flushRow = (advance: number) => {
    if (pieces.length) out.push({ y: rowY, advance, pieces });
    pieces = [];
  };
  for (const line of t.lines) {
    y += line.lead_gap;
    // The paragraph's first row sits at the post-`lead_gap` y (pysdocx adds
    // `space_before` BEFORE laying the line out). `rowY` must follow `y` here,
    // or this row — and the pagination fit check that reads its y — would be
    // short by the paragraph's own `space_before` (dropped headings back onto
    // the previous page). Every later y bump already refreshes `rowY`.
    rowY = y;
    let x0 = line.x_offset;
    let maxWidth = line.max_width;

    if (line.prefix) {
      const prefixSeg: STextSeg = {
        text: line.prefix.text,
        font: line.prefix.font,
        bold: false,
        italic: false,
        underline: false,
        strike: false,
        color: line.prefix.color,
        highlight: null,
      };
      c.font = segFont(prefixSeg);
      const prefixTextW = c.measureText(line.prefix.text).width;
      const prefixW = Math.max(prefixTextW + line.prefix.pt * 0.9, line.prefix.pt * 2.4);
      pieces.push({ seg: prefixSeg, text: line.prefix.text, x: x0 });
      x0 += prefixW;
      maxWidth = Math.max(maxWidth - prefixW, t.min_width);
    }

    // A paragraph only centers/right-aligns when its plain text (measured at
    // the block's base font, not per-run sizes) already fits `maxWidth`
    // unwrapped — a wrapped paragraph stays left-flush (pysdocx rule).
    if (line.align && line.segs.length) {
      c.font = `${t.base_font}px sans-serif`;
      const lineWidth = c.measureText(line.segs.map((s) => s.text).join("")).width;
      if (lineWidth < maxWidth) {
        x0 += line.align === "center" ? (maxWidth - lineWidth) / 2 : maxWidth - lineWidth;
      }
    }

    const rightEdge = x0 + maxWidth;
    let x = x0;
    for (const seg of line.segs) {
      let rest = seg.text;
      while (rest) {
        c.font = segFont(seg);
        const w = c.measureText(rest).width;
        if (x + w <= rightEdge) {
          pieces.push({ seg, text: rest, x });
          x += w;
          rest = "";
          continue;
        }
        const fit = fitPrefix(c, rest, rightEdge - x);
        if (fit <= 0) {
          if (x === x0) {
            // Nothing fits even from the margin: emit one char to guarantee progress.
            const ch = rest.slice(0, 1);
            pieces.push({ seg, text: ch, x });
            x += c.measureText(ch).width;
            rest = rest.slice(1);
          }
          flushRow(line.advance);
          y += line.advance;
          rowY = y;
          x = x0;
          continue;
        }
        // A styled segment that would split mid-word only because the line is
        // already partially filled moves to the next line whole (pysdocx rule).
        if (x > x0 && fit < rest.length && !/[ \t]/.test(rest.slice(0, fit))) {
          if (c.measureText(rest).width <= maxWidth) {
            flushRow(line.advance);
            y += line.advance;
            rowY = y;
            x = x0;
            continue;
          }
        }
        const [head, tail] = wrapCut(rest, fit);
        if (!head) {
          flushRow(line.advance);
          y += line.advance;
          rowY = y;
          x = x0;
          continue;
        }
        c.font = segFont(seg);
        pieces.push({ seg, text: head, x });
        x += c.measureText(head).width;
        if (tail) {
          flushRow(line.advance);
          y += line.advance;
          rowY = y;
          x = x0;
        }
        rest = tail;
      }
    }
    flushRow(line.advance);
    y += line.advance + line.trail_gap;
    rowY = y;
  }
  return out;
}

// Split laid-out rows into page-height bands and keep only band `slot`, rebasing
// each kept row's `y` to the page anchor. Mirrors pysdocx `_paginate_segments`:
// the first row of every band sits at the top margin, and a row is bumped whole
// to the next band when its bottom would cross `band_height - PAGE_PAD`.
function paginateLines(lines: VisLine[], slot: number, bandHeight: number): VisLine[] {
  const bands: VisLine[][] = [];
  let cur: VisLine[] = [];
  let base = 0;
  for (const ln of lines) {
    const absY = TYPED_TEXT_Y0 + ln.y;
    let yPage = absY - base;
    if (cur.length && yPage + ln.advance > bandHeight - TYPED_TEXT_PAGE_PAD) {
      bands.push(cur);
      cur = [];
      base = absY - TYPED_TEXT_Y0;
      yPage = TYPED_TEXT_Y0;
    }
    // Draw offset is measured from the anchor (already at TYPED_TEXT_Y0).
    cur.push({ y: yPage - TYPED_TEXT_Y0, advance: ln.advance, pieces: ln.pieces });
  }
  if (cur.length) bands.push(cur);
  return bands[slot] ?? [];
}

// Lay out and draw one rich text block: rotate around the anchor, then draw each
// visual row's pieces. The document-level typed note body (`t.paginate`) is split
// into page-height bands and only this page's band is drawn.
function drawRichText(c: OffscreenCanvasRenderingContext2D, t: SText, paper: RGB, di: RGB): void {
  c.save();
  c.translate(t.anchor[0], t.anchor[1]);
  if (t.angle_deg) c.rotate((t.angle_deg * Math.PI) / 180);
  c.lineCap = "butt";
  let rows = layoutRichText(c, t);
  if (t.paginate) rows = paginateLines(rows, t.paginate.slot, t.paginate.band_height);
  for (const row of rows) {
    for (const p of row.pieces) {
      drawSegPiece(c, p.seg, p.text, p.x, row.y, paper, di);
    }
  }
  c.restore();
}

self.onmessage = (e: MessageEvent<Job>) => {
  const { id } = e.data;
  try {
    renderJob(e.data);
  } catch {
    // Never let one bad job kill the worker or leave a request unanswered — the
    // main thread treats a missing bitmap as a failure and retries.
    (self as unknown as Worker).postMessage({ id });
  }
};

function renderJob(job: Job): void {
  const { id, scene, scale, images } = job;
  const paper = scene.paper;
  const di = scene.default_ink; // paper-contrast ink (resolved in Rust)
  const bw = Math.max(1, Math.round(scene.width * scale));
  const bh = Math.max(1, Math.round(scene.height * scale));
  const canvas = new OffscreenCanvas(bw, bh);
  const c = canvas.getContext("2d")!;
  c.scale(scale, scale);

  c.fillStyle = css(paper);
  c.fillRect(0, 0, scene.width, scene.height);

  // PDF/custom-image template, pre-rasterized/decoded by the main thread and
  // composited to fill the page under everything.
  if (job.template_bitmap) {
    c.drawImage(job.template_bitmap, 0, 0, scene.width, scene.height);
    job.template_bitmap.close(); // the worker's clone — free it eagerly
  }

  // Built-in "Basic" background template: above the flat fill, below everything else (matches
  // pysdocx render_page, drawn at zorder 0.5). grid = verticals + horizontals; line = horizontals
  // only; dot = a (non-square) lattice of dots; oxford = horizontals + one red margin rule.
  const tpl = scene.template;
  if (tpl?.origin && tpl.row_spacing) {
    const [ox, oy] = tpl.origin;
    const rows = tpl.row_spacing;
    if (tpl.kind === "dot" && tpl.col_spacing) {
      const cols = tpl.col_spacing;
      const r = tpl.dot_radius ?? 2;
      c.fillStyle = rgb(tpl.color ?? null, "#8f98b0");
      for (let y = oy % rows; y <= scene.height + 0.5; y += rows) {
        for (let x = ox % cols; x <= scene.width + 0.5; x += cols) {
          c.beginPath();
          c.arc(x, y, r, 0, Math.PI * 2);
          c.fill();
        }
      }
    } else if (tpl.kind === "grid" || tpl.kind === "line" || tpl.kind === "oxford") {
      const path = new Path2D();
      // Vertical rules only for the square grid (line/oxford have none).
      if (tpl.kind === "grid" && tpl.col_spacing) {
        for (let x = ox % tpl.col_spacing; x <= scene.width + 0.5; x += tpl.col_spacing) {
          path.moveTo(x, 0);
          path.lineTo(x, scene.height);
        }
      }
      for (let y = oy % rows; y <= scene.height + 0.5; y += rows) {
        path.moveTo(0, y);
        path.lineTo(scene.width, y);
      }
      c.strokeStyle = rgb(tpl.color ?? null, "#a6afca");
      c.lineWidth = tpl.line_width ?? 2;
      c.stroke(path);
      // Oxford's single vertical margin rule, in light red.
      if (tpl.kind === "oxford" && tpl.margin_x != null) {
        const margin = new Path2D();
        margin.moveTo(tpl.margin_x, 0);
        margin.lineTo(tpl.margin_x, scene.height);
        c.strokeStyle = rgb(tpl.margin_color ?? null, "#e0a8a8");
        c.lineWidth = (tpl.line_width ?? 2) * 1.6;
        c.stroke(margin);
      }
    }
  }

  const imgMap = new Map(images.map((i) => [i.index, i.bitmap]));
  for (const im of scene.images) {
    const b = imgMap.get(im.media_index);
    if (b) c.drawImage(b, im.x, im.y, im.w, im.h);
  }

  c.lineJoin = "round";
  c.lineCap = "round";
  for (const s of scene.strokes) {
    if (s.points.length === 0) continue;
    const base = Math.max(s.width, 0.5);
    if (s.points.length === 1) {
      c.fillStyle = inkFor(s.color, paper, di);
      c.beginPath();
      c.arc(s.points[0][0], s.points[0][1], base / 2, 0, Math.PI * 2);
      c.fill();
      continue;
    }
    c.strokeStyle = inkFor(s.color, paper, di);
    if (s.tapered && s.pressures && s.pressures.length > 0) {
      drawTapered(c, s, base);
    } else {
      c.lineWidth = base;
      c.stroke(strokePath(s.points, 0, s.points.length - 1));
    }
  }

  // Inserted shapes sit above strokes (pysdocx render_page adds them after the
  // stroke collections at the same z), outline only, round joins like pysdocx.
  for (const s of scene.shapes ?? []) {
    const col = inkFor(s.color, paper, di);
    c.strokeStyle = col;
    c.fillStyle = col;
    c.lineWidth = Math.max(s.width, 0.5);
    drawShape(c, s);
  }

  c.textBaseline = "top";
  for (const t of scene.texts) {
    drawRichText(c, t, paper, di);
  }

  // Tables: grid lines then middle-aligned cell texts (pysdocx render_table;
  // everything is precomputed in the Scene builder).
  for (const tb of scene.tables ?? []) {
    const xs = tb.x_edges, ys = tb.y_edges;
    const x0 = xs[0], x1 = xs[xs.length - 1], y0 = ys[0], y1 = ys[ys.length - 1];
    // Cell background fills sit beneath the borders.
    for (const cell of tb.cells) {
      if (!cell.fill) continue;
      const fx0 = xs[cell.col], fx1 = xs[cell.col + 1];
      const fy0 = ys[cell.row], fy1 = ys[cell.row + 1];
      c.fillStyle = rgb(cell.fill, "#ffffff");
      c.fillRect(fx0, Math.min(fy0, fy1), fx1 - fx0, Math.abs(fy1 - fy0));
    }
    c.lineWidth = tb.line_width;
    const o = tb.outer, inn = tb.inner;
    const outerCol = rgb(o.color, "#b1ac98"), innerCol = rgb(inn.color, "#b1ac98");
    // A full rounded frame draws its own boundary; otherwise a boundary edge is
    // drawn if EITHER the outer frame OR the grid enables it (so "grid horizontal
    // only, no frame" still closes top+bottom). Interior lines are grid-only.
    const rounded = o.has_v && o.has_h && o.radius > 0;
    if (rounded) {
      c.strokeStyle = outerCol;
      c.beginPath();
      c.roundRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0), o.radius);
      c.stroke();
    }
    // Interior grid lines (grid-only).
    c.strokeStyle = innerCol;
    const grid = new Path2D();
    if (inn.has_v) for (let i = 1; i < xs.length - 1; i++) { grid.moveTo(xs[i], y0); grid.lineTo(xs[i], y1); }
    if (inn.has_h) for (let i = 1; i < ys.length - 1; i++) { grid.moveTo(x0, ys[i]); grid.lineTo(x1, ys[i]); }
    c.stroke(grid);
    // Boundary edges (top/bottom, left/right), unless the rounded frame drew them.
    if (!rounded) {
      if (o.has_h || inn.has_h) {
        c.strokeStyle = o.has_h ? outerCol : innerCol;
        const e = new Path2D(); e.moveTo(x0, y0); e.lineTo(x1, y0); e.moveTo(x0, y1); e.lineTo(x1, y1);
        c.stroke(e);
      }
      if (o.has_v || inn.has_v) {
        c.strokeStyle = o.has_v ? outerCol : innerCol;
        const e = new Path2D(); e.moveTo(x0, y0); e.lineTo(x0, y1); e.moveTo(x1, y0); e.lineTo(x1, y1);
        c.stroke(e);
      }
    }
    c.textBaseline = "middle";
    for (const cell of tb.cells) {
      const fg = inkFor(cell.color, paper, di);
      c.fillStyle = fg;
      c.font = `${cell.italic ? "italic " : ""}${cell.bold ? "bold " : ""}${cell.font}px sans-serif`;
      c.fillText(cell.text, cell.x, cell.y);
      // Under/strike span the measured glyph width, not the whole cell.
      if (cell.underline || cell.strikethrough) {
        const w = c.measureText(cell.text).width;
        c.strokeStyle = fg;
        c.lineWidth = 1.0 * 3.4;
        if (cell.underline) { c.beginPath(); c.moveTo(cell.x, cell.y + cell.font * 0.42); c.lineTo(cell.x + w, cell.y + cell.font * 0.42); c.stroke(); }
        if (cell.strikethrough) { c.beginPath(); c.moveTo(cell.x, cell.y); c.lineTo(cell.x + w, cell.y); c.stroke(); }
      }
    }
    c.textBaseline = "top";
  }

  // Sticky notes draw as their collapsed square: decoded bg fill (default
  // sticky yellow) + a dashed contrast border, with a small label — the nested
  // sub-document is not rendered (matches pysdocx's "enumerate them" bar).
  for (const n of scene.sticky_notes ?? []) {
    c.fillStyle = rgb(n.bg_color, "#ffe6ae");
    c.fillRect(n.x, n.y, n.w, n.h);
    // Sticky fill is always light (bg_color or the yellow fallback), so a dark
    // border/label reads regardless of the page paper.
    c.strokeStyle = "#1a1a1a";
    c.lineWidth = 1.0 * 3.4;
    c.setLineDash([10, 8]);
    c.strokeRect(n.x, n.y, n.w, n.h);
    c.setLineDash([]);
    c.fillStyle = "#1a1a1a"; // on the light sticky fill, always dark
    c.font = `${9 * 3.4}px sans-serif`;
    c.fillText("sticky", n.x + 6, n.y + 6);
  }

  const bitmap = canvas.transferToImageBitmap();
  (self as unknown as Worker).postMessage({ id, bitmap }, [bitmap]);
}
