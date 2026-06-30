import init, { render } from "./pkg/sdocx.js";

// --- DOM ---
const stage = document.getElementById("stage");
const viewport = document.getElementById("viewport");
const dropzone = document.getElementById("dropzone");
const toolbar = document.getElementById("toolbar");
const fileNameEl = document.getElementById("file-name");
const pageLabel = document.getElementById("page-label");
const prevBtn = document.getElementById("prev");
const nextBtn = document.getElementById("next");
const fitBtn = document.getElementById("fit");
const exportPngBtn = document.getElementById("export-png");
const exportSvgBtn = document.getElementById("export-svg");
const openBtn = document.getElementById("open");
const pickBtn = document.getElementById("pick");
const fileInput = document.getElementById("file-input");
const messageEl = document.getElementById("message");

// --- State ---
let wasmReady = false;
let pages = []; // [{ width, height, svg }]
let currentPage = 0;
let baseName = "note";
const view = { scale: 1, tx: 0, ty: 0 };

const MIN_SCALE = 0.02;
const MAX_SCALE = 40;

// Kick off WASM init; loads can be queued until it resolves.
const ready = init().then(() => {
  wasmReady = true;
});

// --- Messaging ---
function showMessage(text, kind = "error") {
  messageEl.textContent = text;
  messageEl.className = "message" + (kind === "info" ? " info" : "");
  messageEl.hidden = false;
}
function clearMessage() {
  messageEl.hidden = true;
}

// --- File loading ---
async function loadFile(file) {
  if (!file) return;
  clearMessage();
  baseName = file.name.replace(/\.sdocx$/i, "") || "note";
  try {
    await ready;
    const bytes = new Uint8Array(await file.arrayBuffer());
    const result = render(bytes);
    if (!result || !Array.isArray(result.pages) || result.pages.length === 0) {
      showMessage("Il documento non contiene pagine renderizzabili.");
      return;
    }
    pages = result.pages;
    currentPage = 0;
    fileNameEl.textContent = file.name;
    toolbar.hidden = false;
    dropzone.hidden = true;
    showPage(true);
  } catch (err) {
    console.error(err);
    showMessage(`Impossibile aprire il file: ${err?.message ?? err}`);
  }
}

// --- Rendering a page ---
function showPage(fit) {
  const page = pages[currentPage];
  viewport.style.width = `${page.width}px`;
  viewport.style.height = `${page.height}px`;
  viewport.innerHTML = page.svg;
  const svg = viewport.firstElementChild;
  if (svg && svg.tagName.toLowerCase() === "svg") {
    // Let CSS size the SVG to the viewport box so the transform scales it.
    svg.removeAttribute("width");
    svg.removeAttribute("height");
  }
  updatePager();
  if (fit) fitToStage();
  else applyTransform();
}

function updatePager() {
  pageLabel.textContent = `Pagina ${currentPage + 1} / ${pages.length}`;
  prevBtn.disabled = currentPage <= 0;
  nextBtn.disabled = currentPage >= pages.length - 1;
}

function fitToStage() {
  const page = pages[currentPage];
  const sw = stage.clientWidth;
  const sh = stage.clientHeight;
  const scale = Math.min(sw / page.width, sh / page.height) * 0.95;
  view.scale = clamp(scale, MIN_SCALE, MAX_SCALE);
  view.tx = (sw - page.width * view.scale) / 2;
  view.ty = (sh - page.height * view.scale) / 2;
  applyTransform();
}

function applyTransform() {
  viewport.style.transform =
    `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`;
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

// --- Zoom (wheel, anchored at the pointer) ---
stage.addEventListener(
  "wheel",
  (e) => {
    if (pages.length === 0) return;
    e.preventDefault();
    const rect = stage.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const factor = Math.exp(-e.deltaY * 0.0015);
    const newScale = clamp(view.scale * factor, MIN_SCALE, MAX_SCALE);
    const k = newScale / view.scale;
    // Keep the point under the cursor fixed.
    view.tx = px - (px - view.tx) * k;
    view.ty = py - (py - view.ty) * k;
    view.scale = newScale;
    applyTransform();
  },
  { passive: false },
);

// --- Pan (pointer drag) ---
let panning = false;
let panStart = { x: 0, y: 0, tx: 0, ty: 0 };

stage.addEventListener("pointerdown", (e) => {
  if (pages.length === 0 || e.button !== 0) return;
  panning = true;
  stage.classList.add("panning");
  stage.setPointerCapture(e.pointerId);
  panStart = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
});

stage.addEventListener("pointermove", (e) => {
  if (!panning) return;
  view.tx = panStart.tx + (e.clientX - panStart.x);
  view.ty = panStart.ty + (e.clientY - panStart.y);
  applyTransform();
});

function endPan(e) {
  if (!panning) return;
  panning = false;
  stage.classList.remove("panning");
  try {
    stage.releasePointerCapture(e.pointerId);
  } catch {
    /* pointer already released */
  }
}
stage.addEventListener("pointerup", endPan);
stage.addEventListener("pointercancel", endPan);

// --- Page navigation ---
prevBtn.addEventListener("click", () => {
  if (currentPage > 0) {
    currentPage--;
    showPage(true);
  }
});
nextBtn.addEventListener("click", () => {
  if (currentPage < pages.length - 1) {
    currentPage++;
    showPage(true);
  }
});
fitBtn.addEventListener("click", () => fitToStage());

window.addEventListener("keydown", (e) => {
  if (pages.length === 0) return;
  if (e.key === "ArrowRight" || e.key === "PageDown") nextBtn.click();
  else if (e.key === "ArrowLeft" || e.key === "PageUp") prevBtn.click();
  else if (e.key === "0") fitToStage();
});

// --- Export ---
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function pageSuffix() {
  return pages.length > 1 ? `_page${currentPage}` : "";
}

exportSvgBtn.addEventListener("click", () => {
  if (pages.length === 0) return;
  const blob = new Blob([pages[currentPage].svg], {
    type: "image/svg+xml;charset=utf-8",
  });
  downloadBlob(blob, `${baseName}${pageSuffix()}.svg`);
});

exportPngBtn.addEventListener("click", async () => {
  if (pages.length === 0) return;
  const page = pages[currentPage];
  try {
    const img = new Image();
    img.src =
      "data:image/svg+xml;charset=utf-8," + encodeURIComponent(page.svg);
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = page.width;
    canvas.height = page.height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, page.width, page.height);
    canvas.toBlob((blob) => {
      if (!blob) {
        showMessage("Export PNG non riuscito.");
        return;
      }
      downloadBlob(blob, `${baseName}${pageSuffix()}.png`);
    }, "image/png");
  } catch (err) {
    console.error(err);
    showMessage(`Export PNG non riuscito: ${err?.message ?? err}`);
  }
});

// --- File pickers & drag and drop ---
function openPicker() {
  fileInput.value = "";
  fileInput.click();
}
pickBtn.addEventListener("click", openPicker);
openBtn.addEventListener("click", openPicker);
fileInput.addEventListener("change", (e) => loadFile(e.target.files[0]));

// Drag & drop anywhere on the window.
window.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (dropzone.hidden) return;
  dropzone.classList.add("dragover");
});
window.addEventListener("dragleave", (e) => {
  if (e.relatedTarget === null) dropzone.classList.remove("dragover");
});
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  const file = e.dataTransfer?.files?.[0];
  if (file) loadFile(file);
});

// Re-center on window resize when nothing is being interacted with.
let resizeTimer;
window.addEventListener("resize", () => {
  if (pages.length === 0) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => applyTransform(), 100);
});
