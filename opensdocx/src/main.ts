import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

// ── Types mirroring the Rust Scene (src-tauri/src/lib.rs) ────────────────────
type RGB = [number, number, number];
interface AudioClip { file_id: number; name: string; duration_ms: number; duration_str: string; created_time_us: number }
interface DocMeta { page_count: number; dark_mode: boolean; background: RGB | null; audio: AudioClip[] }
interface Stroke { points: [number, number][]; color: RGB | null; width: number; tapered: boolean; tool_id: number | null; pressures?: number[] }
interface SImage {
  x: number;
  y: number;
  w: number;
  h: number;
  media_index: number;
  angle_deg?: number;
  affine?: [number, number, number, number, number, number];
  crop?: [number, number, number, number];
}
interface SText { anchor: [number, number]; wrap_width: number; angle_deg: number; lines: unknown[] }
// Only the fields the main thread acts on; the full style payload (pitches/colors) is consumed
// by the worker (see render.worker.ts STemplate). kind==="pdf" carries the embedded-PDF link.
interface STemplate { id: number; kind: string; pdf_media_index?: number; pdf_page_index?: number; image_filename?: string }
interface SShape { kind: string; points: [number, number][]; color: RGB | null; width: number; closed: boolean; ellipse?: unknown; round_rect?: unknown; outline?: unknown[]; heads?: [number, number][][] }
interface PageScene { width: number; height: number; paper: RGB; default_ink: RGB; template: STemplate | null; strokes: Stroke[]; images: SImage[]; shapes: SShape[]; texts: SText[] }

const GAP = 16;
const MAX_BITMAP_DIM = 8192; // cap the offscreen raster per page (webview canvas limit)

// ── State ────────────────────────────────────────────────────────────────────
let meta: DocMeta | null = null;
let sizes: [number, number][] = []; // per-page [w, h] in page units
let zoom = 1; // page units -> CSS px
let pageTop: number[] = []; // CSS-px top of each page within #doc
let pageLeft: number[] = []; // CSS-px left of each page within #doc
let rows: number[][] = []; // page indices grouped into layout rows (1 or 2 wide)
let viewMode: "single" | "facing" = "single";
let docWidth = 0;
let docHeight = 0;
// Bumped whenever the layout/zoom changes, so in-flight renders for the old
// scale abort instead of drawing stale bitmaps.
let layoutGen = 0;
let curPage = 0;

// ── Audio playback state ────────────────────────────────────────────────────
const AUDIO_SPEEDS = [1, 1.25, 1.5, 2];
let audioClips: AudioClip[] = [];
let clipStarts: number[] = []; // cumulative ms offset of each clip in the virtual timeline
let totalMs = 0;
let curClip = 0;
let speedIdx = 0;
let audioBarOpen = false;
let audioSeeking = false; // true while the user is dragging the scrub handle
const audioBlobCache = new Map<number, string>(); // file_id -> object URL
const audioEl = new Audio();
audioEl.preload = "auto";

const sceneCache = new Map<number, PageScene>();
const mediaCache = new Map<number, ImageBitmap | null>();
// `bitmap` is kept alive until the slot is replaced/evicted: closing it right
// after drawImage can race WebKitGTK's deferred canvas painting and leave the
// page black.
interface Slot { canvas: HTMLCanvasElement; renderedScale: number; pendingScale: number; retries: number; bitmap: ImageBitmap | null }
const slots = new Map<number, Slot>();
// Cap concurrent page renders so a fast scroll can't flood the pipeline with
// renders of already-passed pages: at most N are ever in flight, the rest are
// kicked (nearest-first) as the pipeline drains. Page parses run in parallel in
// Rust (the Reader lock covers only ZIP extraction), so a small N > 1 pays off.
const MAX_INFLIGHT = 4;
// How many scenes to parse ahead beyond the rendered range, per side. Scenes are
// cheap (no bitmap), so this hides the parse latency when scrolling on.
const PREFETCH_PAGES = 3;
let inFlight = 0;
let visRaf = 0;
function scheduleVisible(): void {
  // A timer, not requestAnimationFrame: WebKitGTK throttles rAF when the page is
  // idle (only resuming on input), which left pages unrendered after a scroll
  // until you clicked. A timeout is not throttled that way.
  if (visRaf) return;
  visRaf = window.setTimeout(() => {
    visRaf = 0;
    updateVisible();
  }, 0);
}

// ── DOM ──────────────────────────────────────────────────────────────────────
const stage = document.querySelector<HTMLElement>("#stage")!;
const docEl = document.querySelector<HTMLElement>("#doc")!;
const emptyEl = document.querySelector<HTMLElement>("#empty")!;
const prevBtn = document.querySelector<HTMLButtonElement>("#prev-btn")!;
const nextBtn = document.querySelector<HTMLButtonElement>("#next-btn")!;
const pageInput = document.querySelector<HTMLInputElement>("#page-input")!;
const pageCount = document.querySelector<HTMLElement>("#page-count")!;
const zoomOut = document.querySelector<HTMLButtonElement>("#zoom-out")!;
const zoomIn = document.querySelector<HTMLButtonElement>("#zoom-in")!;
const zoomInput = document.querySelector<HTMLInputElement>("#zoom-input")!;
const zoomMenuBtn = document.querySelector<HTMLButtonElement>("#zoom-menu-btn")!;
const zoomMenu = document.querySelector<HTMLElement>("#zoom-menu")!;
const audioBtn = document.querySelector<HTMLButtonElement>("#audio-btn")!;
const exportBtn = document.querySelector<HTMLButtonElement>("#export-btn")!;
const exportMenu = document.querySelector<HTMLElement>("#export-menu")!;
const sidebarBtn = document.querySelector<HTMLButtonElement>("#sidebar-btn")!;
const thumbsEl = document.querySelector<HTMLElement>("#thumbs")!;
const viewmodeBtn = document.querySelector<HTMLButtonElement>("#viewmode-btn")!;
// Controls enabled only while a document is open (mirrors the old prev/next/fit).
// audioBtn is NOT here: it's gated on the open note actually having clips
// (see resetAudioState), not on "a document is open" like the others.
const docControls = [prevBtn, nextBtn, pageInput, zoomOut, zoomIn, zoomInput, zoomMenuBtn, exportBtn, sidebarBtn, viewmodeBtn];

const audioBar = document.querySelector<HTMLElement>("#audio-bar")!;
const audioSpeedBtn = document.querySelector<HTMLButtonElement>("#audio-speed")!;
const audioBack10Btn = document.querySelector<HTMLButtonElement>("#audio-back10")!;
const audioPlayPauseBtn = document.querySelector<HTMLButtonElement>("#audio-playpause")!;
const audioFwd10Btn = document.querySelector<HTMLButtonElement>("#audio-fwd10")!;
const audioElapsedEl = document.querySelector<HTMLElement>("#audio-elapsed")!;
const audioTotalEl = document.querySelector<HTMLElement>("#audio-total")!;
const audioScrubTrack = document.querySelector<HTMLElement>("#audio-scrub-track")!;
const audioScrubFill = document.querySelector<HTMLElement>("#audio-scrub-fill")!;
const audioScrubDots = document.querySelector<HTMLElement>("#audio-scrub-dots")!;
const audioScrubHandle = document.querySelector<HTMLElement>("#audio-scrub-handle")!;
const audioListBtn = document.querySelector<HTMLButtonElement>("#audio-list-btn")!;
const audioListMenu = document.querySelector<HTMLElement>("#audio-list-menu")!;

// ── Render worker ────────────────────────────────────────────────────────────
let jobSeq = 0;
const jobs = new Map<number, (bmp: ImageBitmap | null) => void>();
let worker: Worker;
function createWorker(): void {
  worker = new Worker(new URL("./render.worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (e: MessageEvent<{ id: number; bitmap?: ImageBitmap }>) => {
    const cb = jobs.get(e.data.id);
    if (cb) {
      jobs.delete(e.data.id);
      cb(e.data.bitmap ?? null);
    }
  };
  worker.onerror = () => {
    // Worker died (e.g. memory pressure on a big jump): fail everything in
    // flight so slots retry, respawn, and re-render what's visible.
    for (const cb of jobs.values()) cb(null);
    jobs.clear();
    createWorker();
    if (meta) scheduleVisible();
  };
}
createWorker();
function renderViaWorker(
  scene: PageScene,
  scale: number,
  images: { index: number; bitmap: ImageBitmap }[],
  templateBitmap: ImageBitmap | null,
): Promise<ImageBitmap | null> {
  return new Promise((resolve) => {
    const id = ++jobSeq;
    jobs.set(id, resolve);
    // templateBitmap is NOT transferred (structured clone): the cached copy in
    // templateRasterCache must survive for the next render at this zoom.
    worker.postMessage({ id, scene, scale, images, template_bitmap: templateBitmap ?? undefined });
  });
}

// ── Data (cached, on demand) ─────────────────────────────────────────────────
async function getScene(i: number): Promise<PageScene> {
  const cached = sceneCache.get(i);
  if (cached) return cached;
  const s = await invoke<PageScene>("get_page_scene", { index: i });
  sceneCache.set(i, s);
  if (sceneCache.size > 24) {
    for (const k of [...sceneCache.keys()]) {
      if (Math.abs(k - curPage) > 12) sceneCache.delete(k);
    }
  }
  return s;
}

async function loadMediaBitmap(i: number): Promise<ImageBitmap | null> {
  try {
    const m = await invoke<{ mime: string; base64: string }>("get_media", { index: i });
    if (!m.mime.startsWith("image/")) return null;
    const bytes = Uint8Array.from(atob(m.base64), (c) => c.charCodeAt(0));
    return await createImageBitmap(new Blob([bytes], { type: m.mime }));
  } catch {
    return null;
  }
}

async function resolveImages(scene: PageScene): Promise<{ index: number; bitmap: ImageBitmap }[]> {
  const out: { index: number; bitmap: ImageBitmap }[] = [];
  const seen = new Set<number>();
  for (const im of scene.images) {
    if (seen.has(im.media_index)) continue;
    seen.add(im.media_index);
    if (!mediaCache.has(im.media_index)) {
      mediaCache.set(im.media_index, await loadMediaBitmap(im.media_index));
    }
    const b = mediaCache.get(im.media_index);
    if (b) out.push({ index: im.media_index, bitmap: b });
  }
  return out;
}

// ── PDF-backed templates (Academic multi-page / imported PDF) ────────────────
// For template kind==="pdf" the Scene carries (pdf_media_index, pdf_page_index):
// the background artwork is a real PDF embedded under media/ in the archive
// (decoded from the .page header — see crates/sdocx page_pdf_template). PDF.js
// rasterizes the referenced page here, once per zoom level, and the worker
// composites the bitmap under the strokes. PDF.js over native pdfium: nothing
// native to bundle per-OS, and the raster is a one-time cost per (page, zoom)
// hidden by the same cache policy as the page bitmaps themselves.
type PdfJs = typeof import("pdfjs-dist");
type PdfDoc = import("pdfjs-dist").PDFDocumentProxy;
let pdfjsLoad: Promise<PdfJs> | null = null;
function pdfjs(): Promise<PdfJs> {
  // Lazy: notes without PDF templates never pay for loading the library.
  pdfjsLoad ??= (async () => {
    const [lib, workerUrl] = await Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.mjs?url"),
    ]);
    lib.GlobalWorkerOptions.workerSrc = workerUrl.default;
    return lib;
  })();
  return pdfjsLoad;
}
const pdfDocCache = new Map<number, Promise<PdfDoc | null>>();
function getPdfDoc(mediaIndex: number): Promise<PdfDoc | null> {
  let p = pdfDocCache.get(mediaIndex);
  if (!p) {
    p = (async () => {
      try {
        const m = await invoke<{ mime: string; base64: string }>("get_media", { index: mediaIndex });
        const bytes = Uint8Array.from(atob(m.base64), (c) => c.charCodeAt(0));
        return await (await pdfjs()).getDocument({ data: bytes }).promise;
      } catch {
        return null; // missing/corrupt media: page renders without a background
      }
    })();
    pdfDocCache.set(mediaIndex, p);
  }
  return p;
}
// One raster per (media, page), replaced when the zoom scale changes — the same
// once-per-zoom policy as the page bitmaps, so scroll/zoom never re-rasterizes.
const templateRasterCache = new Map<string, { scale: number; bitmap: ImageBitmap }>();
async function resolveTemplateBitmap(scene: PageScene, scale: number): Promise<ImageBitmap | null> {
  const t = scene.template;
  if (t?.kind === "image" && t.image_filename) {
    const key = `image:${t.image_filename}`;
    const hit = templateRasterCache.get(key);
    if (hit) return hit.bitmap;
    try {
      const m = await invoke<{ mime: string; base64: string }>("get_media_by_name", { filename: t.image_filename });
      if (!m.mime.startsWith("image/")) return null;
      const bytes = Uint8Array.from(atob(m.base64), (c) => c.charCodeAt(0));
      const bitmap = await createImageBitmap(new Blob([bytes], { type: m.mime }));
      templateRasterCache.set(key, { scale, bitmap });
      return bitmap;
    } catch {
      return null;
    }
  }
  if (t?.kind !== "pdf" || t.pdf_media_index == null || t.pdf_page_index == null) return null;
  const key = `${t.pdf_media_index}:${t.pdf_page_index}`;
  const hit = templateRasterCache.get(key);
  if (hit && hit.scale === scale) return hit.bitmap;
  const doc = await getPdfDoc(t.pdf_media_index);
  if (!doc || t.pdf_page_index >= doc.numPages) return null;
  const page = await doc.getPage(t.pdf_page_index + 1); // PDF.js pages are 1-based
  const pdfWidth = page.getViewport({ scale: 1 }).width;
  const viewport = page.getViewport({ scale: (scene.width * scale) / pdfWidth });
  const canvas = new OffscreenCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
  // PDF.js v5 renders straight onto a canvas (OffscreenCanvas is supported; the
  // typings only name HTMLCanvasElement, hence the cast).
  await page.render({ canvas: canvas as unknown as HTMLCanvasElement, viewport }).promise;
  const bitmap = canvas.transferToImageBitmap();
  hit?.bitmap.close();
  templateRasterCache.set(key, { scale, bitmap });
  return bitmap;
}

// ── Layout ───────────────────────────────────────────────────────────────────
// Group pages into layout rows: one page per row in single mode, pairs
// [0,1],[2,3],… in facing mode (a trailing odd page sits alone).
function buildRows(): void {
  rows = [];
  if (viewMode === "facing") {
    for (let i = 0; i < sizes.length; i += 2) {
      rows.push(i + 1 < sizes.length ? [i, i + 1] : [i]);
    }
  } else {
    for (let i = 0; i < sizes.length; i++) rows.push([i]);
  }
}
// The pages sharing curPage's row (used by the fit helpers).
function curRowPages(): number[] {
  if (!sizes.length) return [];
  if (viewMode === "facing") {
    const start = curPage - (curPage % 2);
    return start + 1 < sizes.length ? [start, start + 1] : [start];
  }
  return [Math.min(Math.max(curPage, 0), sizes.length - 1)];
}
function computeLayout(): void {
  buildRows();
  pageTop = [];
  pageLeft = [];
  // Row CSS width = summed page widths + inter-page gaps; docWidth centres the
  // widest row (or fills the stage, whichever is larger).
  const rowW = rows.map((r) => r.reduce((s, i) => s + sizes[i][0] * zoom, 0) + GAP * (r.length - 1));
  const maxRowW = rowW.reduce((m, w) => Math.max(m, w), 1);
  docWidth = Math.max(maxRowW + GAP * 2, stage.clientWidth);
  let y = GAP;
  for (let ri = 0; ri < rows.length; ri++) {
    const r = rows[ri];
    let rowH = 0;
    for (const i of r) rowH = Math.max(rowH, sizes[i][1] * zoom);
    let x = Math.round((docWidth - rowW[ri]) / 2);
    for (const i of r) {
      pageLeft[i] = x;
      pageTop[i] = y;
      x += sizes[i][0] * zoom + GAP;
    }
    y += rowH + GAP;
  }
  docHeight = y;
  docEl.style.width = `${docWidth}px`;
  docEl.style.height = `${docHeight}px`;
}
// Fit the current row's width to the stage (a spread of two in facing mode).
function fitZoom(): void {
  const r = curRowPages();
  const sumW = r.reduce((s, i) => s + sizes[i][0], 0) || 1;
  const gaps = GAP * (r.length - 1);
  zoom = (stage.clientWidth - 4 * GAP - gaps) / sumW;
  if (!isFinite(zoom) || zoom <= 0) zoom = 1;
}
// Fit the whole current row (both dimensions) within the stage viewport.
function fitPageZoom(): void {
  const r = curRowPages();
  if (!r.length) { zoom = 1; return; }
  const sumW = r.reduce((s, i) => s + sizes[i][0], 0);
  const maxH = r.reduce((m, i) => Math.max(m, sizes[i][1]), 1);
  const gaps = GAP * (r.length - 1);
  const zw = (stage.clientWidth - 4 * GAP - gaps) / sumW;
  const zh = (stage.clientHeight - 2 * GAP) / maxH;
  zoom = Math.min(zw, zh);
  if (!isFinite(zoom) || zoom <= 0) zoom = 1;
}

// ── Virtualization ───────────────────────────────────────────────────────────
function updateVisible(): void {
  if (!meta) return;
  const dpr = window.devicePixelRatio || 1;
  const scrollTop = stage.scrollTop;
  const vh = stage.clientHeight;
  const centre = scrollTop + vh / 2;
  const margin = vh; // render a screenful above and below
  const top = scrollTop - margin;
  const bot = scrollTop + vh + margin;
  const scale = zoom * dpr;

  const visible: number[] = [];
  for (let i = 0; i < sizes.length; i++) {
    const y0 = pageTop[i];
    const y1 = pageTop[i] + sizes[i][1] * zoom;
    if (y1 >= top && y0 <= bot) visible.push(i);
  }
  const visSet = new Set(visible);
  for (const [i, slot] of slots) {
    if (!visSet.has(i)) {
      slot.bitmap?.close();
      slot.canvas.remove();
      slots.delete(i);
    }
  }
  // Kick nearest-to-viewport-centre first, so with a limited in-flight budget the
  // page the user is looking at always renders before the margin pages.
  const byDistance = [...visible].sort((a, b) => {
    const ca = pageTop[a] + (sizes[a][1] * zoom) / 2;
    const cb = pageTop[b] + (sizes[b][1] * zoom) / 2;
    return Math.abs(ca - centre) - Math.abs(cb - centre);
  });
  for (const i of byDistance) ensureSlot(i, scale);

  if (visible.length > 0) {
    void prefetchScenes(visible[0], visible[visible.length - 1]);
  }

  // Current page = the one crossing the viewport centre.
  let cur = 0;
  for (let i = 0; i < sizes.length; i++) {
    if (pageTop[i] <= centre) cur = i;
    else break;
  }
  if (cur !== curPage) {
    curPage = cur;
    updateNav();
  }
}

// Parse-ahead: warm the scene cache a few pages beyond the rendered range, one at
// a time and only while the render pipeline is idle — visible pages always win.
let prefetching = false;
async function prefetchScenes(lo: number, hi: number): Promise<void> {
  if (prefetching || !meta) return;
  prefetching = true;
  try {
    for (let d = 1; d <= PREFETCH_PAGES; d++) {
      for (const i of [hi + d, lo - d]) {
        if (i < 0 || i >= meta.page_count || sceneCache.has(i)) continue;
        if (inFlight > 0) return; // visible work took over; resume on a later pass
        await getScene(i).catch(() => {});
      }
    }
  } finally {
    prefetching = false;
  }
}

function ensureSlot(i: number, scale: number): void {
  const cssW = sizes[i][0] * zoom;
  const cssH = sizes[i][1] * zoom;
  let slot = slots.get(i);
  if (!slot) {
    const canvas = document.createElement("canvas");
    canvas.className = "pagecanvas";
    docEl.appendChild(canvas);
    slot = { canvas, renderedScale: 0, pendingScale: 0, retries: 0, bitmap: null };
    slots.set(i, slot);
  }
  // Position/size the element (cheap, never clears the drawn bitmap).
  slot.canvas.style.left = `${pageLeft[i]}px`;
  slot.canvas.style.top = `${pageTop[i]}px`;
  slot.canvas.style.width = `${cssW}px`;
  slot.canvas.style.height = `${cssH}px`;
  if (slot.renderedScale === scale || slot.pendingScale === scale) return;
  if (inFlight >= MAX_INFLIGHT) return; // over budget — a later pass will kick it
  renderSlot(i, slot, scale);
}

async function renderSlot(i: number, slot: Slot, scale: number): Promise<void> {
  slot.pendingScale = scale; // in flight — don't kick duplicate renders
  inFlight++;
  const gen = layoutGen;
  // Cap the raster so a tall page at high zoom can't exceed the canvas limit.
  const eff = Math.min(scale, MAX_BITMAP_DIM / sizes[i][0], MAX_BITMAP_DIM / sizes[i][1]);
  // Stale if the layout changed (zoom/resize) or this slot was evicted/replaced.
  const stale = () => gen !== layoutGen || slots.get(i) !== slot;

  try {
    const scene = await getScene(i);
    if (stale()) return;
    const images = await resolveImages(scene);
    if (stale()) return;
    const tplBitmap = await resolveTemplateBitmap(scene, eff);
    if (stale()) return;
    const bitmap = await renderViaWorker(scene, eff, images, tplBitmap);
    if (stale()) {
      bitmap?.close();
      return;
    }
    if (!bitmap) {
      // Worker failed this job — retry a few times, then give up (avoid a loop).
      slot.pendingScale = 0;
      if (slot.retries < 3) slot.retries++;
      else console.warn(`opensdocx: render failed for page ${i} after retries`);
      return;
    }
    // Set the backing store only now, so the previous bitmap stays visible until
    // the new one is ready (no blank flash on zoom/re-render).
    slot.canvas.width = bitmap.width;
    slot.canvas.height = bitmap.height;
    slot.canvas.getContext("2d")!.drawImage(bitmap, 0, 0);
    slot.bitmap?.close();
    slot.bitmap = bitmap; // deferred close — see Slot doc comment
    slot.renderedScale = scale;
    slot.pendingScale = 0;
    slot.retries = 0;
  } finally {
    inFlight--;
    scheduleVisible(); // pump the next queued page (or prefetch) as this frees up
  }
}

// Re-layout everything (after zoom/resize/open): drop slots so they re-render at
// the new scale, then fill what's visible.
function relayout(): void {
  layoutGen++;
  for (const [, slot] of slots) {
    slot.bitmap?.close();
    slot.canvas.remove();
  }
  slots.clear();
  computeLayout();
  updateVisible();
}

// ── Thumbnail side-panel ─────────────────────────────────────────────────────
// A left panel of one small canvas per page, reusing the same scene→worker
// pipeline as the main viewer at a tiny scale. Built lazily (only once the panel
// is first opened) and virtualized (only thumbs near the panel viewport hold a
// rendered bitmap) so a long document stays cheap.
const THUMB_W = 148; // target raster width in CSS px (displayed at 100% of the box)
const THUMB_MAX_INFLIGHT = 2; // keep the shared worker mostly free for the main viewer
interface ThumbSlot { canvas: HTMLCanvasElement; bitmap: ImageBitmap | null }
const thumbEls: HTMLDivElement[] = [];
const thumbSlots = new Map<number, ThumbSlot>();
const thumbInflight = new Set<number>();
let thumbInFlight = 0;
let thumbTop: number[] = []; // CSS-px offsetTop of each thumb within the panel
let thumbH: number[] = [];
let sidebarOpen = false;
let thumbBuilt = false;
let activeThumb = -1;
let thumbRaf = 0;

function scheduleThumbs(): void {
  if (thumbRaf) return;
  thumbRaf = window.setTimeout(() => { thumbRaf = 0; updateThumbs(); }, 0);
}

function clearThumbs(): void {
  for (const s of thumbSlots.values()) s.bitmap?.close();
  thumbSlots.clear();
  thumbInflight.clear();
  thumbEls.length = 0;
  thumbTop = [];
  thumbH = [];
  thumbsEl.replaceChildren();
  thumbBuilt = false;
  activeThumb = -1;
}

function buildThumbs(): void {
  if (!meta) return;
  thumbsEl.replaceChildren();
  thumbEls.length = 0;
  for (let i = 0; i < sizes.length; i++) {
    const div = document.createElement("div");
    div.className = "thumb";
    div.dataset.i = String(i);
    const canvas = document.createElement("canvas");
    canvas.className = "thumb-canvas";
    // Reserve the box height up-front (page aspect ratio) so scroll offsets are
    // stable before any bitmap is drawn.
    canvas.style.aspectRatio = `${sizes[i][0]} / ${sizes[i][1]}`;
    const num = document.createElement("span");
    num.className = "thumb-num";
    num.textContent = String(i + 1);
    div.append(canvas, num);
    thumbsEl.appendChild(div);
    thumbEls.push(div);
  }
  measureThumbs();
  thumbBuilt = true;
  if (curPage >= 0) setActiveThumb(curPage);
}

function measureThumbs(): void {
  thumbTop = thumbEls.map((el) => el.offsetTop);
  thumbH = thumbEls.map((el) => el.offsetHeight);
}

function updateThumbs(): void {
  if (!sidebarOpen || !meta || !thumbBuilt) return;
  const top = thumbsEl.scrollTop;
  const vh = thumbsEl.clientHeight;
  const margin = vh; // a screenful of over-render each side
  const lo = top - margin;
  const hi = top + vh + margin;
  for (let i = 0; i < thumbEls.length; i++) {
    const y0 = thumbTop[i];
    const y1 = thumbTop[i] + thumbH[i];
    const near = y1 >= lo && y0 <= hi;
    if (near) renderThumb(i);
    else if (thumbSlots.has(i)) evictThumb(i); // free bitmaps well off-screen
  }
}

function evictThumb(i: number): void {
  const s = thumbSlots.get(i);
  if (!s) return;
  s.bitmap?.close();
  s.canvas.width = 0;
  s.canvas.height = 0;
  thumbSlots.delete(i);
}

async function renderThumb(i: number): Promise<void> {
  if (thumbSlots.has(i) || thumbInflight.has(i)) return;
  if (thumbInFlight >= THUMB_MAX_INFLIGHT) return; // a later pass will kick it
  thumbInflight.add(i);
  thumbInFlight++;
  const dpr = window.devicePixelRatio || 1;
  const scale = (THUMB_W / sizes[i][0]) * dpr;
  try {
    const scene = await getScene(i);
    if (!sidebarOpen) return;
    const images = await resolveImages(scene);
    if (!sidebarOpen) return;
    const tpl = await resolveTemplateBitmap(scene, scale);
    if (!sidebarOpen) return;
    const bitmap = await renderViaWorker(scene, scale, images, tpl);
    if (!bitmap) return;
    const el = thumbEls[i];
    if (!sidebarOpen || !el) { bitmap.close(); return; }
    const canvas = el.querySelector<HTMLCanvasElement>("canvas.thumb-canvas");
    if (!canvas) { bitmap.close(); return; }
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0);
    // Keep the bitmap alive until eviction — closing right after drawImage can
    // race WebKitGTK's deferred paint and blank the canvas (same as the viewer).
    thumbSlots.set(i, { canvas, bitmap });
  } catch {
    /* transient — a later pass retries */
  } finally {
    thumbInflight.delete(i);
    thumbInFlight--;
    scheduleThumbs();
  }
}

function setActiveThumb(i: number): void {
  if (!thumbBuilt || i === activeThumb) return;
  thumbEls[activeThumb]?.classList.remove("current");
  const el = thumbEls[i];
  if (el) {
    el.classList.add("current");
    if (sidebarOpen) el.scrollIntoView({ block: "nearest" });
  }
  activeThumb = i;
}

function toggleSidebar(): void {
  sidebarOpen = !sidebarOpen;
  thumbsEl.hidden = !sidebarOpen;
  sidebarBtn.classList.toggle("active", sidebarOpen);
  if (sidebarOpen && meta) {
    if (!thumbBuilt) buildThumbs();
    else measureThumbs();
    setActiveThumb(curPage);
    updateThumbs();
  }
  // The stage width changed (panel took/returned space): re-centre & re-render.
  if (meta) relayout();
}

thumbsEl.addEventListener("scroll", scheduleThumbs);
thumbsEl.addEventListener("click", (e) => {
  const el = (e.target as HTMLElement).closest<HTMLElement>(".thumb");
  if (el?.dataset.i) scrollToPage(Number(el.dataset.i));
});

function updateNav(): void {
  if (!meta) return;
  setActiveThumb(curPage);
  // Don't clobber the boxes while the user is typing into them.
  if (document.activeElement !== pageInput) pageInput.value = String(curPage + 1);
  pageCount.textContent = `/ ${meta.page_count}`;
  if (document.activeElement !== zoomInput) zoomInput.value = `${(zoom * 100).toFixed(0)}%`;
  prevBtn.disabled = curPage <= 0;
  nextBtn.disabled = curPage >= meta.page_count - 1;
}

function scrollToPage(i: number): void {
  if (!meta) return;
  i = Math.min(Math.max(i, 0), meta.page_count - 1);
  stage.scrollTo({ top: Math.max(0, pageTop[i] - GAP), behavior: "smooth" });
}

// ── Zoom (anchored on the viewport centre) ───────────────────────────────────
function setZoom(newZoom: number): void {
  if (!meta) return;
  newZoom = Math.min(Math.max(newZoom, 0.05), 20);
  const vh = stage.clientHeight;
  const anchorDocY = stage.scrollTop + vh / 2;
  const ratio = docHeight > 0 ? anchorDocY / docHeight : 0;
  zoom = newZoom;
  relayout();
  stage.scrollTop = Math.max(0, ratio * docHeight - vh / 2);
  updateVisible();
  updateNav();
}

// ── Audio playback ───────────────────────────────────────────────────────────
// Clips are separate .m4a archive members (no single combined media file), so
// a "continuous timeline" is a frontend-only construct: one reused <audio>
// element whose `src` is swapped at clip boundaries, with a virtual position
// (clipStarts[curClip] + audioEl.currentTime*1000) presented as one scrub bar.

// mm:ss (h:mm:ss once an hour is reached), zero-padded like the Samsung UI.
function formatClock(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function parseHms(s: string): number {
  const parts = s.split(":").map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return 0;
  const [h, m, sec] = parts;
  return (h * 3600 + m * 60 + sec) * 1000;
}

// Prefer the authoritative precise_duration_ms; duration_str (HH:MM:SS) is a
// fallback for the (unobserved in-corpus) case where it's non-positive.
function durationMsOf(clip: AudioClip): number {
  return clip.duration_ms > 0 ? clip.duration_ms : parseHms(clip.duration_str);
}

// Recording timestamp, formatted in the viewer's local timezone — the
// authoring device's original tz offset isn't stored in the voice record, so
// exact reproduction of Samsung's displayed time isn't possible.
function formatClipDate(createdUs: number): string {
  const d = new Date(createdUs / 1000);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

function setPlayPauseIcon(playing: boolean): void {
  audioPlayPauseBtn.innerHTML = `<svg class="icon"><use href="#icon-${playing ? "pause" : "play"}" /></svg>`;
  audioPlayPauseBtn.title = playing ? "Pausa" : "Riproduci";
}

function renderScrubDots(): void {
  audioScrubDots.replaceChildren();
  for (let k = 1; k < clipStarts.length; k++) {
    const dot = document.createElement("div");
    dot.className = "audio-scrub-dot";
    dot.style.left = `${totalMs > 0 ? (clipStarts[k] / totalMs) * 100 : 0}%`;
    audioScrubDots.appendChild(dot);
  }
}

function renderClipList(): void {
  audioListMenu.replaceChildren();
  audioClips.forEach((c, i) => {
    const btn = document.createElement("button");
    btn.className = "menu-item audio-clip-item";
    btn.dataset.i = String(i);
    const nameEl = document.createElement("span");
    nameEl.className = "audio-clip-name";
    nameEl.textContent = c.name;
    const metaEl = document.createElement("span");
    metaEl.className = "audio-clip-meta";
    metaEl.textContent = `${formatClock(durationMsOf(c))} · ${formatClipDate(c.created_time_us)}`;
    btn.append(nameEl, metaEl);
    audioListMenu.appendChild(btn);
  });
}

function updateCurrentClipHighlight(): void {
  audioListMenu.querySelectorAll<HTMLElement>(".audio-clip-item").forEach((el, i) => {
    el.classList.toggle("current", i === curClip);
  });
}

function updateScrubUI(virtualMs: number): void {
  const pct = totalMs > 0 ? (Math.min(Math.max(virtualMs, 0), totalMs) / totalMs) * 100 : 0;
  audioScrubFill.style.width = `${pct}%`;
  audioScrubHandle.style.left = `${pct}%`;
  audioElapsedEl.textContent = formatClock(virtualMs);
}

// Last clip whose start offset is <= ms (clamped into range).
function clipIndexAt(ms: number): number {
  let idx = 0;
  for (let i = 0; i < clipStarts.length; i++) {
    if (clipStarts[i] <= ms) idx = i;
    else break;
  }
  return idx;
}

async function clipBlobUrl(fileId: number): Promise<string> {
  const cached = audioBlobCache.get(fileId);
  if (cached) return cached;
  const m = await invoke<{ mime: string; base64: string }>("get_media", { index: fileId });
  const bytes = Uint8Array.from(atob(m.base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: m.mime }));
  audioBlobCache.set(fileId, url);
  return url;
}

// Swap the shared <audio> element onto clip `idx` and wait for it to be
// seekable. playbackRate resets to 1 on every `src` change, so it's re-applied
// here rather than left to the caller.
async function setClipSrc(idx: number): Promise<void> {
  const url = await clipBlobUrl(audioClips[idx].file_id);
  curClip = idx;
  await new Promise<void>((resolve) => {
    audioEl.addEventListener("loadedmetadata", () => resolve(), { once: true });
    audioEl.src = url;
  });
  audioEl.playbackRate = AUDIO_SPEEDS[speedIdx];
  updateCurrentClipHighlight();
}

async function advanceToNextClip(): Promise<void> {
  const next = curClip + 1;
  if (next >= audioClips.length) return;
  await setClipSrc(next);
  audioEl.currentTime = 0;
  try {
    await audioEl.play();
  } catch {
    /* autoplay blocked — user can press play */
  }
}

function currentVirtualMs(): number {
  return clipStarts[curClip] + audioEl.currentTime * 1000;
}

async function seekTo(virtualMs: number, opts: { play?: boolean } = {}): Promise<void> {
  if (!audioClips.length) return;
  virtualMs = Math.min(Math.max(virtualMs, 0), totalMs);
  const idx = clipIndexAt(virtualMs);
  const localSec = (virtualMs - clipStarts[idx]) / 1000;
  if (idx !== curClip || !audioEl.src) {
    await setClipSrc(idx);
  }
  audioEl.currentTime = localSec;
  updateScrubUI(virtualMs);
  const shouldPlay = opts.play ?? !audioEl.paused;
  if (shouldPlay) {
    try {
      await audioEl.play();
    } catch {
      /* autoplay blocked — user can press play */
    }
  } else {
    audioEl.pause();
  }
}

function toggleAudioBar(): void {
  if (audioBtn.disabled) return;
  audioBarOpen = !audioBarOpen;
  audioBar.hidden = !audioBarOpen;
  audioBtn.classList.toggle("active", audioBarOpen);
}

// Rebuild all audio state for the freshly opened document (called from
// loadDocument). Revokes blob URLs from the previous document and resets the
// shared <audio> element, mirroring the cache-clearing block around it.
function resetAudioState(): void {
  audioEl.pause();
  stopScrubLoop();
  audioEl.removeAttribute("src");
  audioEl.load();
  for (const url of audioBlobCache.values()) URL.revokeObjectURL(url);
  audioBlobCache.clear();

  audioClips = meta?.audio ?? [];
  clipStarts = [];
  let acc = 0;
  for (const c of audioClips) {
    clipStarts.push(acc);
    acc += durationMsOf(c);
  }
  totalMs = acc;
  curClip = 0;
  speedIdx = 0;
  audioSpeedBtn.textContent = "1x";
  setPlayPauseIcon(false);

  audioBtn.disabled = audioClips.length === 0;
  audioBtn.title = audioClips.length === 0 ? "Nessuna registrazione audio" : "Audio";
  if (audioClips.length === 0 && audioBarOpen) {
    audioBarOpen = false;
    audioBar.hidden = true;
    audioBtn.classList.remove("active");
  }

  renderScrubDots();
  renderClipList();
  updateScrubUI(0);
  audioTotalEl.textContent = formatClock(totalMs);
}

// `timeupdate` only fires a few times a second — driving the scrub bar off it
// alone reads as stepped/jerky. While playing, repaint every animation frame
// instead; `timeupdate` stays as the catch-up source while paused (e.g. right
// after a seek, before any frame loop is running).
let scrubRaf = 0;
function scrubTick(): void {
  if (!audioSeeking) updateScrubUI(currentVirtualMs());
  scrubRaf = requestAnimationFrame(scrubTick);
}
function startScrubLoop(): void {
  if (!scrubRaf) scrubRaf = requestAnimationFrame(scrubTick);
}
function stopScrubLoop(): void {
  if (scrubRaf) cancelAnimationFrame(scrubRaf);
  scrubRaf = 0;
}

audioEl.addEventListener("timeupdate", () => {
  if (audioSeeking || scrubRaf) return;
  updateScrubUI(currentVirtualMs());
});
audioEl.addEventListener("play", () => {
  setPlayPauseIcon(true);
  startScrubLoop();
});
audioEl.addEventListener("pause", () => {
  setPlayPauseIcon(false);
  stopScrubLoop();
  updateScrubUI(currentVirtualMs());
});
audioEl.addEventListener("ended", () => {
  if (curClip + 1 < audioClips.length) void advanceToNextClip();
});

audioBtn.addEventListener("click", toggleAudioBar);
audioSpeedBtn.addEventListener("click", () => {
  speedIdx = (speedIdx + 1) % AUDIO_SPEEDS.length;
  audioSpeedBtn.textContent = `${AUDIO_SPEEDS[speedIdx]}x`;
  audioEl.playbackRate = AUDIO_SPEEDS[speedIdx];
});
audioPlayPauseBtn.addEventListener("click", () => {
  if (!audioClips.length) return;
  if (!audioEl.src) {
    void seekTo(0, { play: true });
    return;
  }
  if (audioEl.paused) audioEl.play().catch(() => {});
  else audioEl.pause();
});
audioBack10Btn.addEventListener("click", () => {
  void seekTo(currentVirtualMs() - 10_000, { play: !audioEl.paused });
});
audioFwd10Btn.addEventListener("click", () => {
  void seekTo(currentVirtualMs() + 10_000, { play: !audioEl.paused });
});
audioListBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleMenu(audioListMenu);
});
audioListMenu.addEventListener("click", (e) => {
  const item = (e.target as HTMLElement).closest<HTMLElement>(".audio-clip-item");
  if (!item?.dataset.i) return;
  const idx = Number(item.dataset.i);
  void seekTo(clipStarts[idx], { play: true });
});

// Scrub track: pointerdown seeks immediately (a plain click), drag previews
// the position live and commits the seek on release.
let scrubWasPlaying = false;
function scrubFractionAt(clientX: number): number {
  const rect = audioScrubTrack.getBoundingClientRect();
  return Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
}
audioScrubTrack.addEventListener("pointerdown", (e) => {
  if (!audioClips.length) return;
  audioSeeking = true;
  scrubWasPlaying = !audioEl.paused;
  audioScrubTrack.setPointerCapture(e.pointerId);
  updateScrubUI(scrubFractionAt(e.clientX) * totalMs);
});
audioScrubTrack.addEventListener("pointermove", (e) => {
  if (!audioSeeking) return;
  updateScrubUI(scrubFractionAt(e.clientX) * totalMs);
});
audioScrubTrack.addEventListener("pointerup", (e) => {
  if (!audioSeeking) return;
  audioSeeking = false;
  void seekTo(scrubFractionAt(e.clientX) * totalMs, { play: scrubWasPlaying });
});

// ── Open ─────────────────────────────────────────────────────────────────────
async function openFile(): Promise<void> {
  const selected = await open({ multiple: false, filters: [{ name: "Samsung Notes", extensions: ["sdocx"] }] });
  if (!selected || Array.isArray(selected)) return;
  await loadDocument(selected);
}

async function loadDocument(selected: string): Promise<void> {
  meta = await invoke<DocMeta>("open_document", { path: selected });
  sizes = await invoke<[number, number][]>("get_page_sizes");
  resetAudioState();
  sceneCache.clear();
  for (const b of mediaCache.values()) b?.close();
  mediaCache.clear();
  for (const p of pdfDocCache.values()) p.then((d) => void d?.destroy().catch(() => {}));
  pdfDocCache.clear();
  for (const r of templateRasterCache.values()) r.bitmap.close();
  templateRasterCache.clear();
  clearThumbs();
  curPage = 0;
  emptyEl.hidden = true;
  for (const c of docControls) c.disabled = false;
  fitZoom();
  stage.scrollTop = 0;
  relayout();
  if (sidebarOpen) { buildThumbs(); updateThumbs(); }
  updateNav();
}

// ── Wiring ───────────────────────────────────────────────────────────────────
document.querySelector("#open-btn")!.addEventListener("click", () => {
  openFile().catch((err) => alert(String(err)));
});
prevBtn.addEventListener("click", () => scrollToPage(curPage - 1));
nextBtn.addEventListener("click", () => scrollToPage(curPage + 1));

// Editable current-page box: commit on Enter/blur, revert on Escape.
function commitPageInput(): void {
  const n = parseInt(pageInput.value, 10);
  if (Number.isFinite(n)) scrollToPage(n - 1);
  updateNav(); // normalize the box back to the clamped current page
}
pageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); pageInput.blur(); }
  else if (e.key === "Escape") { updateNav(); pageInput.blur(); }
});
pageInput.addEventListener("blur", commitPageInput);

// Zoom −/+ (mirror the Ctrl +/- keyboard steps).
zoomOut.addEventListener("click", () => setZoom(zoom / 1.1));
zoomIn.addEventListener("click", () => setZoom(zoom * 1.1));

// Typeable zoom %: commit on Enter/blur, revert on Escape.
function commitZoomInput(): void {
  const n = parseFloat(zoomInput.value.replace("%", "").replace(",", "."));
  if (Number.isFinite(n) && n > 0) setZoom(n / 100);
  else updateNav();
}
zoomInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); zoomInput.blur(); }
  else if (e.key === "Escape") { updateNav(); zoomInput.blur(); }
});
zoomInput.addEventListener("blur", commitZoomInput);

// Dropdown menus (zoom presets/fit + export stub). Only one open at a time.
function closeMenus(): void { zoomMenu.hidden = true; exportMenu.hidden = true; audioListMenu.hidden = true; }
function toggleMenu(menu: HTMLElement): void {
  const willOpen = menu.hidden;
  closeMenus();
  menu.hidden = !willOpen;
}
zoomMenuBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(zoomMenu); });
zoomMenu.addEventListener("click", (e) => {
  const item = (e.target as HTMLElement).closest<HTMLElement>(".menu-item");
  if (!item || !meta) return;
  const v = item.dataset.zoom!;
  if (v === "fit-width") { fitZoom(); setZoom(zoom); }
  else if (v === "fit-page") { fitPageZoom(); setZoom(zoom); }
  else setZoom(parseFloat(v) / 100);
  closeMenus();
});
exportBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(exportMenu); });
sidebarBtn.addEventListener("click", toggleSidebar);
// Single ↔ facing (continuous two-column). Re-fit to the new mode's width and
// keep the current page in view; single-mode layout stays byte-identical.
viewmodeBtn.addEventListener("click", () => {
  if (!meta) return;
  viewMode = viewMode === "single" ? "facing" : "single";
  viewmodeBtn.classList.toggle("active", viewMode === "facing");
  viewmodeBtn.title = viewMode === "facing" ? "Pagina singola" : "Pagine affiancate";
  fitZoom();
  relayout();
  stage.scrollTop = Math.max(0, pageTop[curPage] - GAP);
  updateVisible();
  updateNav();
});
// Dismiss any open menu on an outside click.
window.addEventListener("click", closeMenus);

stage.addEventListener("scroll", scheduleVisible);

// Dev affordance: `VITE_OPEN_FILE=/abs/path.sdocx npm run tauri dev` auto-opens a
// file at startup (optionally jumping to 1-based page VITE_OPEN_PAGE), so the
// render-verification workflow can drive the app without clicking through the
// dialog. Unset in production builds; the dialog stays the normal path.
const autoOpen = import.meta.env.VITE_OPEN_FILE as string | undefined;
if (autoOpen) {
  loadDocument(autoOpen)
    .then(() => {
      const page = Number(import.meta.env.VITE_OPEN_PAGE ?? "");
      if (page >= 2) scrollToPage(page - 1);
    })
    .catch((err) => alert(String(err)));
}

// Ctrl/Cmd + wheel = zoom; plain wheel scrolls natively.
window.addEventListener("wheel", (e) => {
  if (!meta || !(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  setZoom(zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
}, { passive: false, capture: true });

// Trackpad pinch (WebKit) — block so it doesn't zoom the UI (see lib.rs too).
for (const type of ["gesturestart", "gesturechange", "gestureend"]) {
  window.addEventListener(type, (e) => e.preventDefault(), { passive: false, capture: true });
}

window.addEventListener("resize", () => {
  if (!meta) return;
  relayout();
  if (sidebarOpen && thumbBuilt) { measureThumbs(); updateThumbs(); }
});
window.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); setZoom(zoom * 1.1); return; }
  if (mod && e.key === "-") { e.preventDefault(); setZoom(zoom / 1.1); return; }
  if (mod && e.key === "0") { e.preventDefault(); if (meta) { fitZoom(); setZoom(zoom); } return; }
  if (!meta) return;
  if (e.key === "ArrowRight" || e.key === "PageDown") scrollToPage(curPage + 1);
  else if (e.key === "ArrowLeft" || e.key === "PageUp") scrollToPage(curPage - 1);
}, { capture: true });
