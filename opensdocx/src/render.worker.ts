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
interface PageScene {
  width: number;
  height: number;
  background: RGB | null;
  strokes: Stroke[];
  images: SImage[];
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
