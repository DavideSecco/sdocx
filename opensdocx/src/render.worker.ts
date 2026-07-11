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
interface STextLine { advance: number; segs: STextSeg[] }
interface SText { anchor: [number, number]; wrap_width: number; angle_deg: number; lines: STextLine[] }
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
// underline segment) from the Scene builder; the worker only strokes the grid
// and fills the texts.
interface STableCell {
  x: number;
  y: number;
  text: string;
  font: number;
  bold: boolean;
  italic: boolean;
  color: RGB | null;
  underline?: [number, number, number]; // x0, x1, y
}
interface STable { x_edges: number[]; y_edges: number[]; line_color: RGB; line_width: number; cells: STableCell[] }
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
  /** Pre-rasterized PDF-template background (kind==="pdf"), from PDF.js on the
   * main thread. A structured clone of the cached bitmap — the worker owns it. */
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

// Lay out and draw one rich text block: rotate around the anchor, then flow
// each line's styled segments with measured wrapping (pysdocx
// _render_rich_text's segment loop, paragraphs excluded — text boxes have none).
function drawRichText(c: OffscreenCanvasRenderingContext2D, t: SText, paper: RGB, di: RGB): void {
  c.save();
  c.translate(t.anchor[0], t.anchor[1]);
  if (t.angle_deg) c.rotate((t.angle_deg * Math.PI) / 180);
  c.lineCap = "butt";
  let y = 0;
  for (const line of t.lines) {
    let x = 0;
    for (const seg of line.segs) {
      let rest = seg.text;
      while (rest) {
        c.font = segFont(seg);
        const w = c.measureText(rest).width;
        if (x + w <= t.wrap_width) {
          x += drawSegPiece(c, seg, rest, x, y, paper, di);
          rest = "";
          continue;
        }
        const fit = fitPrefix(c, rest, t.wrap_width - x);
        if (fit <= 0) {
          if (x === 0) {
            // Nothing fits even from the margin: draw one char to guarantee progress.
            x += drawSegPiece(c, seg, rest.slice(0, 1), x, y, paper, di);
            rest = rest.slice(1);
          }
          x = 0;
          y += line.advance;
          continue;
        }
        // A styled segment that would split mid-word only because the line is
        // already partially filled moves to the next line whole (pysdocx rule).
        if (x > 0 && fit < rest.length && !/[ \t]/.test(rest.slice(0, fit))) {
          if (c.measureText(rest).width <= t.wrap_width) {
            x = 0;
            y += line.advance;
            continue;
          }
        }
        const [head, tail] = wrapCut(rest, fit);
        if (!head) {
          x = 0;
          y += line.advance;
          continue;
        }
        x += drawSegPiece(c, seg, head, x, y, paper, di);
        if (tail) {
          x = 0;
          y += line.advance;
        }
        rest = tail;
      }
    }
    y += line.advance;
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

  // PDF-backed template (Academic multi-page / imported PDF): pre-rasterized by
  // the main thread (PDF.js), composited to fill the page under everything —
  // mirrors pysdocx rasterize_pdf_page. The PDF page is A4, the same aspect as
  // the sdocx page, so stretching to (width, height) does not distort.
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
    c.strokeStyle = rgb(tb.line_color, "#8a8f9a");
    c.lineWidth = tb.line_width;
    const grid = new Path2D();
    for (const x of xs) {
      grid.moveTo(x, ys[0]);
      grid.lineTo(x, ys[ys.length - 1]);
    }
    for (const y of ys) {
      grid.moveTo(xs[0], y);
      grid.lineTo(xs[xs.length - 1], y);
    }
    c.stroke(grid);
    c.textBaseline = "middle";
    for (const cell of tb.cells) {
      const fg = inkFor(cell.color, paper, di);
      c.fillStyle = fg;
      c.font = `${cell.italic ? "italic " : ""}${cell.bold ? "bold " : ""}${cell.font}px sans-serif`;
      c.fillText(cell.text, cell.x, cell.y);
      if (cell.underline) {
        c.strokeStyle = fg;
        c.lineWidth = 1.0 * 3.4;
        c.beginPath();
        c.moveTo(cell.underline[0], cell.underline[2]);
        c.lineTo(cell.underline[1], cell.underline[2]);
        c.stroke();
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
