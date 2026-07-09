# The sdocx viewer app — development plan

The **product** section of the repo, separate from the format knowledge base
([`docs/format/`](../format/)). `docs/format/` answers *"what do the bytes mean"*;
this is the single, living plan for the app built on top of them.

> **This is a living document.** Keep it current: tick milestones as they land,
> and append to the Decision log whenever we settle (or reverse) a choice. It is
> the handoff between sessions for the app work, the way `future_todo.md` is for
> the format RE.
>
> Status legend: ☐ todo · ◐ in progress · ☑ done. Last updated 2026-07-09.

---

## 1. Vision

**OpenSdocx** — *"Open Samsung Notes, anywhere."* A **standalone, multiplatform,
open-source desktop app** that opens a Samsung Notes `.sdocx` and shows it **faithful to the eye** for every content type, stays
**fluid on heavy notes**, and lets you **export, select/search text, and play
audio**. It is the tool that finally opens these files on a computer, where no
viewer exists today (on the Samsung device itself, Samsung Notes already does).

**Mission:** this is its **own standalone product** — not a contribution
upstreamed to `twangodev/sdocx` — with the explicit goal of becoming **the
standard open-source way to open Samsung Notes**. That raises the bar on identity
(its own name/brand), trust (open-source, files never leave the device), complete
format coverage, and reach (all desktop OSes).

Editing notes is the **north star** but is gated on reverse-engineering the
*write* path (and the 32-byte hash, likely a device HMAC) — explicitly **not** in
near-term scope.

## 2. Priorities (fixed, in order)

1. **Correctness / fidelity** — "faithful to the eye" (the level `pysdocx`
   already reaches), *not* pixel-perfect vs Samsung (needs proprietary fonts;
   not worth it).
2. **Performance / smoothness** — instant and smooth even on heavy notes
   (benchmark: 48 pages, ~11,788 objects).
3. **Beauty** — a polished UI, after the two above.

Cross-cutting: **multiplatform**, **public open-source release**, **Linux-first**
for development and testing.

## 3. v1 scope

**In scope — faithful render of all corpus content:** strokes (with pressure),
imported images, inserted shapes, typed text + tables, grid/templates, sticky
notes, embedded audio. Plus:

- View: zoom, pan, multi-page navigation.
- **Export**: PDF (multipage) / PNG / SVG.
- **Text layer**: select + copy typed text, and full-text search.
- **Audio**: play embedded `.m4a` attachments.

**Out of scope for v1 (non-goals):** editing / writing `.sdocx`; mobile; pixel-
perfect rasterization; any cloud upload or telemetry (files never leave the
device).

## 4. Decisions taken

Recorded so we don't relitigate them; reversals go in the Decision log (§10).

- **Core language = Rust.** The perf bottleneck is *rendering vectors at 60fps*,
  not parsing (12k objects parse in milliseconds in any compiled language). C
  gives no speed edge here, loses memory safety on untrusted binary input, and
  would discard the already-validated Rust parser + renderer. Non-Rust cores
  (Qt/C++, Wails/Go, Avalonia/C#, Flutter, Electron) all mean rewriting that and
  re-earning fidelity for no decisive win.
- **Mobile is out** (for now). A desktop app does *not* run on phones; mobile is
  a separate build/target. Low value anyway (Samsung Notes exists on the device).
  The UI-agnostic core (below) keeps a future mobile frontend cheap to add.
- **UI stack = Tauri, pending a perf-spike confirmation.** Rust core + web UI in a
  native shell. Chosen because the v1 features (text select/search, PDF export,
  audio, polished UI) are nearly free in a web UI and hand-built in native GPU,
  while fidelity is identical either way. **Tauri is a genuine native standalone
  app** (own binary/window/file-association), not a website — the only difference
  vs native-GPU is *how the window is painted* (system webview vs Rust GPU).
- **Native-GPU (Slint/iced + wgpu) stays an open door.** If the perf-spike shows
  the webview can't hold 60fps on the benchmark, we swap the *frontend* to
  Slint+wgpu — without redoing fidelity, because the core is UI-agnostic.
- **Keep the core UI-agnostic via a `Scene` model** (§6). ~90% of the effort
  (parser, format logic, fidelity, the diff harness) is shared across any
  frontend; switching stacks later re-does only draw calls.
- **Frontend tooling = Vite + TypeScript, vanilla** (no heavy framework yet). The
  app is canvas-centric; the chrome is light. Add Svelte later only if the UI
  grows.
- **`pysdocx` = best current reference implementation**, not the product and not
  the definition of truth. Truth is the ground-truth (how Samsung actually renders,
  captured in `samples/*_gt/`) + the decoded format; `pysdocx` renders it near-
  perfectly but has heuristics and known gaps, so it is a fast regression baseline,
  not infallible. Where the two disagree, ground-truth wins (§7).
- **The existing `viewer/` (browser + WASM) is reference only** — the app is built
  fresh and properly, not by patching it. The Rust core is reused directly
  (native, no WASM).

## 5. Repo layout (target)

```
app/                     # the Tauri v2 project (new)
  index.html
  package.json           # Vite + TS; @tauri-apps/cli as dev dep
  vite.config.ts
  src/                   # frontend (TypeScript)
    main.ts
    render/              # Scene -> <canvas> drawing (strokes, shapes, text, images, grid)
    viewer/              # page virtualization, zoom/pan, navigation
    features/            # text layer + search, export, audio player
  src-tauri/             # Rust backend (workspace member)
    Cargo.toml           # deps: sdocx, sdocx-render/-scene (path), tauri, serde
    src/
      main.rs
      commands.rs        # open_document, get_page_scene, media, export, search
crates/
  sdocx/                 # parser (exists) — decoded format facts = part of the truth

  sdocx-render/          # SVG renderer (exists) — gains the Scene model (or a new crate does)
  sdocx-scene/           # OPTIONAL new crate: UI-agnostic Scene + Document->Scene builder
  sdocx-cli, sdocx-wasm  # exist
pysdocx/                 # reference impl + regression baseline (not the truth)
tools/                   # render-diff harness (pysdocx vs app renderer)
```

**Update (2026-07-06):** the app lives in **`opensdocx/`** (not `app/`) and is its
**own Cargo workspace** — the root workspace `exclude`s it — so the RE workspace's
CI stays light and OpenSdocx is already decoupled for its future standalone repo.
`opensdocx/src-tauri` depends on the core crates by path (`../../crates/sdocx`,
feature `serde`). Layout: `opensdocx/{index.html, src/ (Vite+TS frontend),
src-tauri/ (Rust backend)}`.

## 6. Architecture

### The `Scene` model (the UI-agnostic contract)

The core parses a `.sdocx` and produces a serializable **display list** that
knows nothing about how it will be drawn. Sketch:

```
Scene        { title, page_size_default, dark_mode, background, pages[], media[] }
Page         { width, height, template: Option<Template>, elements[] (z-ordered) }
Template     { kind: Grid|Pdf|None, spacing, color, origin }
Element =
  | Stroke   { points: [(x,y,pressure)], color, width, tool_id }
  | Shape    { kind, outline: [(x,y)], closed, stroke, width, fill?, arrows }
  | Image    { bbox, media_index, rotation }
  | Text     { blocks: [{ pos, runs: [{ text, size, bold/italic/underline/strike,
                          color, highlight }], align, indent }] , layer_geometry }
MediaAsset   { index, name, mime, kind: Image|Audio, bytes|ref }
```

- **Rendering logic (smoothing, shape geometry, grid pitch, text layout, pagination)
  lives in Rust**, in the Scene builder — the same logic `pysdocx` prototyped, so
  it can be checked against `pysdocx` (baseline) and, ultimately, ground-truth
  (§7). The frontend is a thin drawer.
- Serialized as JSON to start (simple); switch to a compact binary (msgpack) only
  if profiling says so.

### Data flow

1. User opens a file → Tauri command `open_document(path)` → `sdocx` parses →
   builder returns **Scene metadata** (pages, sizes, per-page element counts,
   media manifest) — *not* every page's geometry up front.
2. Frontend renders **only visible pages**; for each, calls `get_page_scene(i)`,
   caches the result, evicts offscreen pages. This virtualization is what keeps
   heavy notes smooth.
3. Media (images/audio) delivered via a Tauri asset URL / command returning bytes.

### Frontend rendering

- One `<canvas>` per *visible* page, sized to page dims × zoom × devicePixelRatio.
  Offscreen pages are placeholder divs (correct size, not drawn).
- Strokes: Catmull-Rom smoothed, variable width from pressure. Shapes, images,
  grid, text drawn from the Scene.
- Zoom/pan via the scroll container + re-raster at zoom for crispness.
- **Text layer**: transparent, absolutely-positioned HTML text over the canvas
  (PDF.js style) → real selection/copy + search highlight. This is the concrete
  reason the web UI wins for our feature set.

## 7. Correctness methodology (priority #1)

**What "correct" means.** The ground truth is the *actual Samsung Notes rendering*
— captured as the ground-truth photos in `samples/*_gt/` — plus the **decoded
format facts** in `docs/format/`. That is the real bar. `pysdocx` is our **best
current reference implementation**: it renders the format near-photographically,
but it is *not* infallible — it carries render heuristics and known gaps (e.g.
absolute-f64 strokes, rotated text-box wrapping). So it is a *baseline*, not the
definition of truth.

Two tiers, used together:

- **Fast regression gate — diff vs `pysdocx` (automated, whole corpus).** For each
  corpus page, render the reference image with `pysdocx` and the same page through
  the app's Scene renderer (headless — Scene→image), compute SSIM + pixel diff,
  and **fail past a threshold**. Cheap, deterministic, CI-friendly — the twin of
  `tests/test_kaitai_spec.py`. It catches *divergence from the known-good baseline*
  on every content-type port, so no port silently regresses.
- **Fidelity bar — vs ground-truth photos (the actual truth).** For the pages we
  have GT photos, the real fidelity judgment is against those. Where `pysdocx` and
  GT disagree, **GT wins** — and we fix `pysdocx` too, since it stays the shared
  render logic in the Scene builder. New GT samples raise the bar for both.

Every content-type port (§9, Phase 1) lands only when its diff-vs-pysdocx passes
and, where a GT photo exists, it matches GT.

Headless rendering of the Scene for the diff: decide in Phase 1 between (a) a Rust
Scene→SVG path rasterized with `resvg`, or (b) driving the real canvas headless.
Prefer (a) — fast, deterministic, and it exercises the shared Scene→raster logic.

## 8. Testing & CI

- **Rust:** `cargo nextest run` — Scene-builder unit tests + the diff harness
  (skips cleanly when sample images are absent, like the Kaitai gate).
- **Frontend:** minimal to start; Playwright smoke test later.
- **CI:** build the Tauri app on Linux first (webkit2gtk-4.1 present); add
  macOS/Windows runners in Phase 4.

## 9. Roadmap (vertical-slice sequencing — app alive early, then grows)

Each phase ends with a concrete, checkable deliverable.

- **☐ Phase 0 — App alive + perf spike.**
  Scaffold `app/` (Tauri v2, Vite+TS). Backend `open_document` + `get_page_scene`
  over the workspace `sdocx`. Frontend opens a real `.sdocx` via native dialog and
  renders page 1 (strokes + images — already supported), with zoom/pan/page-nav
  and page virtualization. Load the **benchmark** and **measure frame-time** on
  scroll/zoom — and also **spot-check rendering consistency across at least two
  webviews** (Linux WebKitGTK + Windows WebView2), since that is the real test of
  the Tauri bet (risk ① in §12), not just fps.
  *Done when:* the app opens a real file natively and shows page 1 faithfully, and
  we have a measured 60fps + cross-webview-consistency verdict on the benchmark
  (→ confirm Tauri or trigger the native-GPU fallback).

- **◐ Phase 1 — Fidelity (priority #1).**
  Build the pysdocx-vs-app **render-diff harness** first. Then port one content
  type at a time into the Scene builder, each gated by a passing diff:
  shapes → grid/template → typed text + pagination → tables → sticky → absolute-f64
  strokes → audio indicators.
  *Done when:* the whole corpus renders in-app matching pysdocx within threshold.
  *Progress (2026-07-08):* **grid/template ☑** (SceneTemplate carries grid
  kind/spacing/origin/color/line-width, worker draws it) and **shapes ☑** (parser
  ported to `crates/sdocx` — `PageElement::Shape`, gated by a 384/384 field-level
  parity test vs a pysdocx fixture — plus `SceneShape` with geometry resolved in
  Rust and the worker drawer). The image render-diff harness was deferred (see
  Decision log); these two ports are gated by the parser parity test + scene unit
  tests + visual check vs pysdocx renders instead.
  *Progress (2026-07-09):* **text boxes ☑** (parser rewritten to pysdocx parity —
  marker-based text, full TLV style runs incl. underline/strike/per-run
  colors/highlights/font-sizes, header-decoded rotation + frame midpoints; 8/8
  boxes byte-equal vs the pysdocx fixture in `crates/sdocx/tests/text_boxes.rs`;
  `SceneText` resolves anchor/wrap/rotation + styled segments in Rust, the worker
  does measured wrapping + decorations), **sticky notes ☑**
  (`PageElement::StickyNote` from the `co_attach_file` property-bag scan, 3/3
  placements vs pysdocx in `tests/sticky_notes.rs`; drawn as the collapsed square
  with the decoded `skn_bg_color` fill + dashed border) and **tables ☑**
  (`parse_tables` port — anchor-clustered grid + per-cell whole-cell styles,
  gated by `tests/tables.rs` vs the pysdocx fixture 18/18 cells; `SceneTable`
  resolves grid + shrink-to-fit cell fonts, placement uses pysdocx's
  page-heuristic). Remaining in Phase 1: typed-text pagination + substitute
  font, absolute-f64 strokes (blocked on a sample), audio indicators, and the
  deferred SSIM harness.

- **☐ Phase 2 — Performance (priority #2).**
  Confirm/optimize lazy per-page rendering; resolve any SVG-vs-canvas or
  JSON-vs-binary questions on measured numbers; cache/evict tuning.
  *Done when:* the benchmark opens fast and scrolls smooth (target 60fps).

- **☐ Phase 3 — App features.**
  Text layer → select/copy + full-text search; export PDF/PNG/SVG; audio player.
  *Done when:* all §3 features work on the corpus.

- **☐ Phase 4 — Public product.**
  Packaging (Linux-first: AppImage/flatpak → macOS/Windows), CI release pipeline,
  UI polish (priority #3), README + announcement.
  *Done when:* installable builds exist for the three desktop OSes and the repo
  presents the app as a product.

- **☐ Later — Editing (north star).** Needs write-path RE + the HMAC question.

## 10. Decision log

Append-only; newest last. Record what changed and why.

- **2026-07-06** — Pivot from format-documentation to building the app (morale +
  turning invisible RE into a usable product). Core=Rust; mobile out; UI=Tauri
  pending perf-spike; native-GPU kept as fallback; core UI-agnostic via `Scene`;
  frontend=Vite+TS vanilla; pysdocx=oracle; build fresh (not patch `viewer/`).
  Toolchain: Rust 1.96, Node 20, npm; Tauri installed; webkit2gtk-4.1/gtk3/librsvg
  present on the Arch dev box (no sudo needed).
- **2026-07-06** — Risk review (§12). Decisions: keep **Tauri**, no Electron (too
  heavy); the swappable frontend is our insurance against risk ①. **Render
  heuristics computed once in Rust** (Scene builder = single source), so
  canvas/SVG/PDF match (risk ②). The diff gate stays an SVG proxy but we add
  periodic real-canvas eyeballing (risk ③). Proprietary Samsung fonts can't be
  bundled (licensing); typed text uses an **open substitute font, recalibrated** —
  deferred to Phase 1/3 (risk ④). Handwriting search is out of scope (risk ⑤).
  Zoom tiling handled in Phase 2 (risk ⑥). Big-note transport/cache deferred, door
  kept open (risk ⑦). **Principle adopted now: the parser preserves opaque/unknown
  byte spans** so future editing (writer/round-trip) stays feasible (risk ⑧).

- **2026-07-08** — Phase 1 kickoff, harness deferred (user decision): grid/template
  and shapes were ported **without** the §7 image-diff harness this round; the gate
  is (a) a field-level parser parity test vs a pysdocx-generated fixture
  (`crates/sdocx/tests/shapes.rs`, 384/384 shapes on the two shape samples),
  (b) Scene-builder unit tests in `opensdocx/src-tauri`, and (c) manual visual
  comparison vs pysdocx renders. The SSIM harness remains the Phase-1 backbone and
  should come next. Per risk ②, all grid/shape render heuristics (grid pitch/origin/
  color, the matplotlib-pt→page-unit factor 3.40, arrowhead sizing) live in the
  Scene builder (`opensdocx/src-tauri/src/lib.rs`), flagged `⚠ Heuristic`; the
  worker draws only what the Scene says. Dev affordance added: `VITE_OPEN_FILE`
  (+ optional `VITE_OPEN_PAGE`) auto-opens a file in `tauri dev` for verification.

- **2026-07-09** — Phase 1 round 2 (text boxes / sticky notes / tables), still
  without the §7 image-diff harness (same gate as 2026-07-08: parser parity
  fixtures + scene unit tests + manual visual check). Notable choices:
  (a) the `crates/sdocx` text-box parser was **rewritten to pysdocx parity**
  (object-header bbox/rotation/frame-midpoints instead of the legacy heuristic
  scan) and the TLV style-run scanner is now **shared** between page text boxes
  and note.note typed text; (b) rich-text **glyph measurement stays in the
  worker** (canvas `measureText`) while everything else (anchor, wrap width,
  per-run styles, line advances, shrink-to-fit table fonts) is resolved in the
  Rust Scene builder — same split as stroke smoothing (risk ②), to be
  centralized when the SVG/diff path is built; (c) sticky notes render as their
  collapsed square **filled with the decoded `skn_bg_color`** (Android ARGB
  color-int in the attachment property bag, `-6482` = the default sticky
  yellow — ⚠ interpretation verified on 3/3 records, one distinct value seen);
  (d) tables keep pysdocx's **page-placement heuristic** ("pagina N" in the
  typed text → page N−1, else page 4) — note.note has no page reference for
  document-level content, so any placement is a render decision; (e) tables use
  the scan-based `parse_tables` model, NOT the byte-exact type-22 object parse —
  the latter needs the full sequential note-doc port, which lands with the
  typed-text work.

## 10b. Rendering architecture (decided 2026-07-07)

The viewer is a **continuous, virtualized, worker-rendered document** (PDF.js-style),
not a single-page view — chosen so it never dead-ends when continuous scroll is
needed:

- **Continuous scroll**: all pages stacked vertically; page-nav = "jump to page".
- **Virtualized**: only pages in/near the viewport are rendered; others are
  correctly-sized placeholders → scales to 66+ page notes.
- **Exact layout up front**: all page sizes are read cheaply from each `.page`
  header (~30 bytes, no stroke parse) via `Reader::page_size` / a `get_page_sizes`
  command, so the scroll column has no reflow jumps.
- **Rasterize in a Web Worker (OffscreenCanvas)**: scene→bitmap happens off the
  main thread, so scroll/zoom never freeze; neighbours are pre-rasterized.
- Reused unchanged: the Rust lazy `Reader` + `Scene` + parser (incl. the O(n²)
  fix), async commands, scene cache, and the Scene→canvas drawing logic (which
  moves into the worker). Only the frontend *view layer* is rebuilt.

Lesson driving this: don't ship half-measures that win now but block the
continuous view later (user, 2026-07-07).

## 11. Open decisions (to resolve as we hit them)

1. **Perf-spike verdict** → confirm Tauri, or switch frontend to Slint+wgpu.
2. **Scene home** → extend `sdocx-render` vs a new `crates/sdocx-scene`.
3. **Headless diff rendering** → Rust Scene→SVG+`resvg` vs headless canvas.
4. **PDF export mechanism** → webview print-to-PDF vs a Rust PDF crate
   (`printpdf`/`svg2pdf`).
5. **Scene transport** → JSON now; msgpack only if profiling demands.

## 12. Known risks & limitations

Red-teamed 2026-07-06. Severity: 🔴 structural · 🟠 watch · 🟡 minor. Each has a
disposition; we address them in the phase noted, not all now.

1. 🔴 **Tauri uses the *system* webview → three rendering engines** (WebKitGTK /
   WKWebView / WebView2). "One codebase" still means per-OS differences in canvas,
   text metrics, blend modes, print-to-PDF — exactly where fidelity/perf live.
   Native-GPU (Slint) or bundled-Chromium would be more consistent.
   *Disposition:* accepted; the swappable frontend (UI-agnostic Scene) is the
   insurance. The Phase-0 spike must also check cross-webview consistency, not just
   fps. No Electron (too heavy).
2. 🟠 **Where render heuristics live** (smoothing, pressure taper, width clamps,
   highlighter blend). If duplicated per frontend, the SVG rasterizer and canvas
   can diverge. Baking geometry in Rust = consistent but resolution-locked (worse
   deep-zoom sharpness); drawing-time = crisp but must be identical everywhere.
   *Disposition:* computed once in Rust (Scene builder, single source). Blend-mode
   parity across canvas / SVG / resvg is a specific thing to verify.
3. 🟠 **The diff gate validates the SVG path, not the shipped canvas pixels.** Gate
   can be green while the canvas app is wrong if the two drawers diverge.
   *Disposition:* accept the proxy for the automated gate; add periodic
   real-canvas visual checks.
4. 🟠 **Typed text depends on fonts we don't have.** Samsung's fonts are
   proprietary (can't bundle — licensing); pysdocx's pagination constants are
   matplotlib-tuned; webview fonts differ per OS; the text layer must align to the
   drawn glyphs for select/search. (Handwriting is vector strokes — unaffected.)
   *Disposition:* pick + bundle an open substitute font and recalibrate pagination
   to it. Deferred to Phase 1/3.
5. 🟡 **Full-text search covers typed text only** — strokes are not text (no OCR).
   *Disposition:* accepted limitation; set expectations. OCR out of scope.
6. 🟠 **Canvas zoom = re-raster + max-canvas-size limit.** Raster blurs on zoom
   (redraw needed); a very dense page redrawn per zoom tick can jank; deep zoom can
   exceed the browser's max canvas dimensions.
   *Disposition:* debounced redraw from the client-side Scene + tiling past a zoom
   threshold (standard technique). Phase 2.
7. 🟡 **IPC serialization + memory on huge notes.** Fast-scrolling many pages =
   many Scene→JSON→parse hits; caching hundreds of page-scenes grows memory.
   *Disposition:* deferred, door kept open — cache eviction + neighbor prefetch +
   async parse with progress; binary transport only if profiling demands.
8. 🟠 **The `Scene` is a lossy *render* projection → wrong model for editing.**
   Editing needs a round-trippable document model that preserves structure and the
   bytes we don't yet decode, plus a writer. The Scene will never be that model.
   *Disposition:* principle adopted now — **the parser preserves opaque/unknown
   byte spans** (cheap today) so a future writer can round-trip. The editable
   document model itself is future work (north star).

   *Update 2026-07-07:* stroke **Catmull-Rom smoothing + pressure-width** was first
   implemented in the canvas frontend (`opensdocx/src/main.ts`) for the visual win;
   per the risk ② decision it will be centralized into the shared render logic when
   the SVG/diff-harness path is built (Phase 1).
9. 🟡 **Touch-SCREEN pinch still zooms the whole UI** (Linux/WebKitGTK). The Rust
   fix (opensdocx/src-tauri/src/lib.rs) pins the WebKit zoom level (Ctrl+scroll,
   Ctrl +/-) and swallows *touchpad* pinch (GDK `TouchpadPinch`), but a
   **touchscreen** pinch goes through a different GTK gesture path and is not
   intercepted, so it scales the toolbar too.
   *Disposition:* accepted/deferred (2026-07-06, user) — low priority; revisit with
   UX polish. Document zoom otherwise works via Ctrl+scroll / Ctrl +/-.

## 13. Product identity

- **2026-07-06** — Decided: the app is its **own standalone product**, completely
  separate from `twangodev/sdocx` (not upstreamed). Goal: become **the standard
  open-source Samsung Notes viewer**. Implies its own name/brand and, eventually,
  its own repository.
- **2026-07-06** — Name decided: **OpenSdocx** — anchored on the `.sdocx`
  extension ("Open" = open the file *and* open source); avoids "viewer" so it can
  grow toward editing; trademark-safe (evokes Samsung Notes via the tagline, not
  the name). Tagline: **"Open Samsung Notes, anywhere."** Technical ids:
  package/crate `opensdocx`, bundle id `dev.opensdocx.app` (changeable).
  **Still open:** app license; when to split into a dedicated repo.
