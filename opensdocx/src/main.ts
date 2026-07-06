import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

// ── Types mirroring the Rust `Scene` (src-tauri/src/lib.rs) ──────────────────
type RGB = [number, number, number];
interface PageMeta { width: number; height: number; stroke_count: number; element_count: number }
interface DocMeta { page_count: number; dark_mode: boolean; background: RGB | null; pages: PageMeta[] }
interface Stroke { points: [number, number][]; pressures: number[]; color: RGB | null; width: number; tapered: boolean; tool_id: number | null }
interface SImage { x: number; y: number; w: number; h: number; media_index: number }
interface SText { x: number; y: number; w: number; h: number; text: string; color: RGB | null; font_size: number | null; rotation: number | null }
interface PageScene {
  width: number; height: number; background: RGB | null;
  template: { id: number; kind: string } | null;
  strokes: Stroke[]; images: SImage[]; texts: SText[];
}

// ── State ────────────────────────────────────────────────────────────────────
let meta: DocMeta | null = null;
let pageIndex = 0;
let zoom = 1;
let fit = true;
const mediaCache = new Map<number, HTMLImageElement | null>();

const canvas = document.querySelector<HTMLCanvasElement>("#page")!;
const ctx = canvas.getContext("2d")!;
const stage = document.querySelector<HTMLElement>("#stage")!;
const emptyEl = document.querySelector<HTMLElement>("#empty")!;
const stat = document.querySelector<HTMLElement>("#stat")!;
const pageLabel = document.querySelector<HTMLElement>("#page-label")!;
const prevBtn = document.querySelector<HTMLButtonElement>("#prev-btn")!;
const nextBtn = document.querySelector<HTMLButtonElement>("#next-btn")!;
const fitBtn = document.querySelector<HTMLButtonElement>("#fit-btn")!;

function rgb(c: RGB | null, fallback: string): string {
  return c ? `rgb(${c[0]},${c[1]},${c[2]})` : fallback;
}
function inkColor(c: RGB | null, dark: boolean): string {
  return rgb(c, dark ? "#ffffff" : "#1a1a1a");
}

async function loadMedia(i: number): Promise<HTMLImageElement | null> {
  if (mediaCache.has(i)) return mediaCache.get(i)!;
  try {
    const m = await invoke<{ mime: string; base64: string }>("get_media", { index: i });
    if (!m.mime.startsWith("image/")) { mediaCache.set(i, null); return null; }
    const img = new Image();
    img.src = `data:${m.mime};base64,${m.base64}`;
    await img.decode().catch(() => {});
    mediaCache.set(i, img);
    return img;
  } catch {
    mediaCache.set(i, null);
    return null;
  }
}

async function renderPage(): Promise<void> {
  if (!meta) return;
  const scene = await invoke<PageScene>("get_page_scene", { index: pageIndex });
  const dpr = window.devicePixelRatio || 1;

  if (fit) {
    const pad = 32;
    const availW = stage.clientWidth - pad;
    const availH = stage.clientHeight - pad;
    zoom = Math.min(availW / scene.width, availH / scene.height);
    if (!isFinite(zoom) || zoom <= 0) zoom = 1;
  }

  const cssW = scene.width * zoom;
  const cssH = scene.height * zoom;
  canvas.style.width = `${cssW}px`;
  canvas.style.height = `${cssH}px`;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.hidden = false;
  emptyEl.hidden = true;

  const t0 = performance.now();
  ctx.setTransform(dpr * zoom, 0, 0, dpr * zoom, 0, 0);

  // Background (page bg, else document bg, else theme default).
  const bg = scene.background ?? meta.background;
  ctx.fillStyle = rgb(bg, meta.dark_mode ? "#252525" : "#ffffff");
  ctx.fillRect(0, 0, scene.width, scene.height);

  // Images under everything else.
  for (const im of scene.images) {
    const img = await loadMedia(im.media_index);
    if (img) ctx.drawImage(img, im.x, im.y, im.w, im.h);
  }

  // Strokes (Phase 0: simple polylines; smoothing/pressure land in Phase 1).
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (const s of scene.strokes) {
    if (s.points.length === 0) continue;
    ctx.strokeStyle = inkColor(s.color, meta.dark_mode);
    ctx.lineWidth = Math.max(s.width, 0.5);
    ctx.beginPath();
    ctx.moveTo(s.points[0][0], s.points[0][1]);
    if (s.points.length === 1) {
      ctx.lineTo(s.points[0][0] + 0.01, s.points[0][1] + 0.01);
    } else {
      for (let i = 1; i < s.points.length; i++) ctx.lineTo(s.points[i][0], s.points[i][1]);
    }
    ctx.stroke();
  }

  // Typed text (Phase 0: naive top-left placement; real layout is Phase 1).
  ctx.textBaseline = "top";
  for (const tx of scene.texts) {
    if (!tx.text.trim()) continue;
    ctx.fillStyle = inkColor(tx.color, meta.dark_mode);
    const fs = tx.font_size ?? 30;
    ctx.font = `${fs}px sans-serif`;
    let y = tx.y;
    for (const line of tx.text.split("\n")) {
      ctx.fillText(line, tx.x, y);
      y += fs * 1.3;
    }
  }

  const dt = performance.now() - t0;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  stat.textContent =
    `pag ${pageIndex + 1}/${meta.page_count} · ${scene.strokes.length} tratti · ` +
    `${scene.images.length} img · render ${dt.toFixed(1)} ms · zoom ${(zoom * 100).toFixed(0)}%`;
}

function updateNav(): void {
  if (!meta) return;
  pageLabel.textContent = `${pageIndex + 1} / ${meta.page_count}`;
  prevBtn.disabled = pageIndex <= 0;
  nextBtn.disabled = pageIndex >= meta.page_count - 1;
  fitBtn.disabled = false;
}

function goto(i: number): void {
  if (!meta) return;
  pageIndex = Math.min(Math.max(i, 0), meta.page_count - 1);
  fit = true;
  updateNav();
  void renderPage();
}

async function openFile(): Promise<void> {
  const selected = await open({
    multiple: false,
    filters: [{ name: "Samsung Notes", extensions: ["sdocx"] }],
  });
  if (!selected || Array.isArray(selected)) return;
  meta = await invoke<DocMeta>("open_document", { path: selected });
  pageIndex = 0;
  fit = true;
  mediaCache.clear();
  updateNav();
  await renderPage();
}

// ── Wiring ─────────────────────────────────────────────────────────────────
document.querySelector("#open-btn")!.addEventListener("click", () => {
  openFile().catch((err) => alert(String(err)));
});
prevBtn.addEventListener("click", () => goto(pageIndex - 1));
nextBtn.addEventListener("click", () => goto(pageIndex + 1));
fitBtn.addEventListener("click", () => { fit = true; void renderPage(); });

function zoomBy(factor: number): void {
  if (!meta) return;
  fit = false;
  zoom = Math.min(Math.max(zoom * factor, 0.05), 20);
  void renderPage();
}

// Ctrl/Cmd + wheel = zoom the CANVAS (document) only. The webview's own page-zoom
// is pinned to 100% in the Rust backend (see lib.rs), so the UI never scales.
window.addEventListener("wheel", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1);
}, { passive: false, capture: true });

// Trackpad pinch on WebKit fires non-standard gesture events; block them so the
// whole UI never pinch-zooms (document zoom stays on the canvas / Ctrl +/-).
for (const type of ["gesturestart", "gesturechange", "gestureend"]) {
  window.addEventListener(type, (e) => e.preventDefault(), { passive: false, capture: true });
}

window.addEventListener("resize", () => { if (meta && fit) void renderPage(); });
window.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  // Ctrl/Cmd +/-/0 = canvas zoom in / out / fit (preventDefault stops any native).
  if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); zoomBy(1.1); return; }
  if (mod && e.key === "-") { e.preventDefault(); zoomBy(1 / 1.1); return; }
  if (mod && e.key === "0") { e.preventDefault(); if (meta) { fit = true; void renderPage(); } return; }
  if (!meta) return;
  if (e.key === "ArrowRight") goto(pageIndex + 1);
  else if (e.key === "ArrowLeft") goto(pageIndex - 1);
  else if (e.key === "0") { fit = true; void renderPage(); }
}, { capture: true });
