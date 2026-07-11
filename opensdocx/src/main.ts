import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

// ── Types mirroring the Rust Scene (src-tauri/src/lib.rs) ────────────────────
type RGB = [number, number, number];
interface DocMeta { page_count: number; dark_mode: boolean; background: RGB | null }
interface Stroke { points: [number, number][]; color: RGB | null; width: number; tapered: boolean; tool_id: number | null; pressures?: number[] }
interface SImage { x: number; y: number; w: number; h: number; media_index: number }
interface SText { anchor: [number, number]; wrap_width: number; angle_deg: number; lines: unknown[] }
// Only the fields the main thread acts on; the full style payload (pitches/colors) is consumed
// by the worker (see render.worker.ts STemplate). kind==="pdf" carries the embedded-PDF link.
interface STemplate { id: number; kind: string; pdf_media_index?: number; pdf_page_index?: number }
interface SShape { kind: string; points: [number, number][]; color: RGB | null; width: number; closed: boolean; ellipse?: unknown; round_rect?: unknown; outline?: unknown[]; heads?: [number, number][][] }
interface PageScene { width: number; height: number; paper: RGB; default_ink: RGB; template: STemplate | null; strokes: Stroke[]; images: SImage[]; shapes: SShape[]; texts: SText[] }

const GAP = 16;
const MAX_BITMAP_DIM = 8192; // cap the offscreen raster per page (webview canvas limit)

// ── State ────────────────────────────────────────────────────────────────────
let meta: DocMeta | null = null;
let sizes: [number, number][] = []; // per-page [w, h] in page units
let zoom = 1; // page units -> CSS px
let pageTop: number[] = []; // CSS-px top of each page within #doc
let docWidth = 0;
let docHeight = 0;
// Bumped whenever the layout/zoom changes, so in-flight renders for the old
// scale abort instead of drawing stale bitmaps.
let layoutGen = 0;
let curPage = 0;

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
const stat = document.querySelector<HTMLElement>("#stat")!;
const pageLabel = document.querySelector<HTMLElement>("#page-label")!;
const prevBtn = document.querySelector<HTMLButtonElement>("#prev-btn")!;
const nextBtn = document.querySelector<HTMLButtonElement>("#next-btn")!;
const fitBtn = document.querySelector<HTMLButtonElement>("#fit-btn")!;

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
function computeLayout(): void {
  let y = GAP;
  let maxW = 1;
  pageTop = [];
  for (let i = 0; i < sizes.length; i++) {
    pageTop[i] = y;
    y += sizes[i][1] * zoom + GAP;
    maxW = Math.max(maxW, sizes[i][0] * zoom);
  }
  docHeight = y;
  docWidth = Math.max(maxW + GAP * 2, stage.clientWidth);
  docEl.style.width = `${docWidth}px`;
  docEl.style.height = `${docHeight}px`;
}
function pageX(i: number): number {
  return Math.round((docWidth - sizes[i][0] * zoom) / 2);
}
function fitZoom(): void {
  const w = sizes[0]?.[0] ?? 1;
  zoom = (stage.clientWidth - 4 * GAP) / w;
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
  slot.canvas.style.left = `${pageX(i)}px`;
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

function updateNav(): void {
  if (!meta) return;
  pageLabel.textContent = `${curPage + 1} / ${meta.page_count}`;
  prevBtn.disabled = curPage <= 0;
  nextBtn.disabled = curPage >= meta.page_count - 1;
  fitBtn.disabled = false;
  stat.textContent = `pag ${curPage + 1}/${meta.page_count} · zoom ${(zoom * 100).toFixed(0)}%`;
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

// ── Open ─────────────────────────────────────────────────────────────────────
async function openFile(): Promise<void> {
  const selected = await open({ multiple: false, filters: [{ name: "Samsung Notes", extensions: ["sdocx"] }] });
  if (!selected || Array.isArray(selected)) return;
  await loadDocument(selected);
}

async function loadDocument(selected: string): Promise<void> {
  meta = await invoke<DocMeta>("open_document", { path: selected });
  sizes = await invoke<[number, number][]>("get_page_sizes");
  sceneCache.clear();
  for (const b of mediaCache.values()) b?.close();
  mediaCache.clear();
  for (const p of pdfDocCache.values()) p.then((d) => void d?.destroy().catch(() => {}));
  pdfDocCache.clear();
  for (const r of templateRasterCache.values()) r.bitmap.close();
  templateRasterCache.clear();
  curPage = 0;
  emptyEl.hidden = true;
  fitZoom();
  stage.scrollTop = 0;
  relayout();
  updateNav();
}

// ── Wiring ───────────────────────────────────────────────────────────────────
document.querySelector("#open-btn")!.addEventListener("click", () => {
  openFile().catch((err) => alert(String(err)));
});
prevBtn.addEventListener("click", () => scrollToPage(curPage - 1));
nextBtn.addEventListener("click", () => scrollToPage(curPage + 1));
fitBtn.addEventListener("click", () => { if (meta) { fitZoom(); setZoom(zoom); } });

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

window.addEventListener("resize", () => { if (meta) relayout(); });
window.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); setZoom(zoom * 1.1); return; }
  if (mod && e.key === "-") { e.preventDefault(); setZoom(zoom / 1.1); return; }
  if (mod && e.key === "0") { e.preventDefault(); if (meta) { fitZoom(); setZoom(zoom); } return; }
  if (!meta) return;
  if (e.key === "ArrowRight" || e.key === "PageDown") scrollToPage(curPage + 1);
  else if (e.key === "ArrowLeft" || e.key === "PageUp") scrollToPage(curPage - 1);
}, { capture: true });
