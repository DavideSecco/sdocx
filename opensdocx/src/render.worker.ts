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
interface SText { x: number; y: number; w: number; h: number; text: string; color: RGB | null; font_size: number | null }
// Grid style (spacing/origin/color/line_width) comes fully resolved from the Rust
// Scene builder — no style constants here (single source, docs/app/README.md risk ②).
interface STemplate { id: number; kind: string; spacing?: number; origin?: [number, number]; color?: RGB; line_width?: number }
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
interface PageScene {
  width: number;
  height: number;
  background: RGB | null;
  template: STemplate | null;
  strokes: Stroke[];
  images: SImage[];
  shapes: SShape[];
  texts: SText[];
}
interface Job {
  id: number;
  scene: PageScene;
  scale: number; // device px per page unit
  darkMode: boolean;
  docBg: RGB | null;
  images: { index: number; bitmap: ImageBitmap }[];
}

function rgb(c: RGB | null, fb: string): string {
  return c ? `rgb(${c[0]},${c[1]},${c[2]})` : fb;
}
function ink(c: RGB | null, dark: boolean): string {
  return rgb(c, dark ? "#ffffff" : "#1a1a1a");
}
// A shape whose stored color matches the canvas exactly is using the "default ink"
// indicator, not a deliberate same-as-background color — fall back to a contrasting
// ink (mirrors pysdocx render_shape; a failed color scan defaults to 37,37,37 there).
function shapeInk(c: RGB | null, bg: RGB | null, dark: boolean): string {
  const eff: RGB = c ?? [37, 37, 37];
  const bgEff: RGB = bg ?? (dark ? [37, 37, 37] : [255, 255, 255]);
  if (eff[0] === bgEff[0] && eff[1] === bgEff[1] && eff[2] === bgEff[2]) {
    return dark ? "#ffffff" : "#1a1a1a";
  }
  return rgb(eff, "#1a1a1a");
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
  const { id, scene, scale, darkMode, docBg, images } = job;
  const bw = Math.max(1, Math.round(scene.width * scale));
  const bh = Math.max(1, Math.round(scene.height * scale));
  const canvas = new OffscreenCanvas(bw, bh);
  const c = canvas.getContext("2d")!;
  c.scale(scale, scale);

  const bg = scene.background ?? docBg;
  c.fillStyle = rgb(bg, darkMode ? "#252525" : "#ffffff");
  c.fillRect(0, 0, scene.width, scene.height);

  // Squared-paper template: above the flat fill, below everything else (matches
  // pysdocx render_page, grid at zorder 0.5).
  const tpl = scene.template;
  if (tpl?.kind === "grid" && tpl.spacing) {
    const [ox, oy] = tpl.origin ?? [0, 0];
    const grid = new Path2D();
    for (let x = ox % tpl.spacing; x <= scene.width + 0.5; x += tpl.spacing) {
      grid.moveTo(x, 0);
      grid.lineTo(x, scene.height);
    }
    for (let y = oy % tpl.spacing; y <= scene.height + 0.5; y += tpl.spacing) {
      grid.moveTo(0, y);
      grid.lineTo(scene.width, y);
    }
    c.strokeStyle = rgb(tpl.color ?? null, "#d3dae8");
    c.lineWidth = tpl.line_width ?? 2;
    c.stroke(grid);
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
      c.fillStyle = ink(s.color, darkMode);
      c.beginPath();
      c.arc(s.points[0][0], s.points[0][1], base / 2, 0, Math.PI * 2);
      c.fill();
      continue;
    }
    c.strokeStyle = ink(s.color, darkMode);
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
    const col = shapeInk(s.color, bg, darkMode);
    c.strokeStyle = col;
    c.fillStyle = col;
    c.lineWidth = Math.max(s.width, 0.5);
    drawShape(c, s);
  }

  c.textBaseline = "top";
  for (const t of scene.texts) {
    if (!t.text.trim()) continue;
    c.fillStyle = ink(t.color, darkMode);
    const fs = t.font_size ?? 30;
    c.font = `${fs}px sans-serif`;
    let y = t.y;
    for (const line of t.text.split("\n")) {
      c.fillText(line, t.x, y);
      y += fs * 1.3;
    }
  }

  const bitmap = canvas.transferToImageBitmap();
  (self as unknown as Worker).postMessage({ id, bitmap }, [bitmap]);
}
