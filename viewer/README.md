# sdocx web viewer

A zero-build, browser-based viewer for Samsung Notes `.sdocx` files. It parses
and renders entirely in your browser using the project's WASM bindings — no file
ever leaves your device.

Features: drag & drop / file picker, scroll to zoom, drag to pan, multi-page
navigation, and export of the current page to PNG or SVG.

## How it works

The viewer calls `render()` from the `sdocx-wasm` bindings, which run the **same
SVG renderer as the CLI** (`crates/sdocx-render`). It then displays that SVG and
adds zoom/pan/export on top. Rendering (strokes with pressure, rich text,
embedded images, dark-mode backgrounds) is therefore identical to the CLI output.

## Build the WASM package

The viewer imports `./pkg/sdocx.js`, produced by `wasm-pack` with the **`web`**
target (note: the npm release uses the default *bundler* target — that won't work
for this no-bundler viewer). Just run the build script:

```sh
# one-time tooling (Arch Linux):
#   sudo pacman -S wasm-pack rust-wasm
# or with rustup:
#   cargo install wasm-pack && rustup target add wasm32-unknown-unknown

./viewer/build.sh    # works from any directory
```

This generates `viewer/pkg/` (`sdocx.js`, `sdocx_bg.wasm`, type defs). The folder
is git-ignored — regenerate it whenever the Rust code changes.

> Running `wasm-pack` by hand? Its `--out-dir` is resolved **relative to the
> crate directory**, not your shell's cwd. From the repo root the correct
> invocation is therefore:
> `wasm-pack build crates/sdocx-wasm --target web --out-name sdocx --out-dir ../../viewer/pkg`
> The `build.sh` script uses absolute paths to avoid this pitfall.

## Run it

WASM modules cannot load from `file://`, so serve the folder over HTTP:

```sh
cd viewer
python -m http.server 8000
# then open http://localhost:8000
```

Drag a `.sdocx` onto the page (try the files in `../samples/`).

## Controls

- **Scroll** — zoom (anchored at the cursor)
- **Drag** — pan
- **Adatta** / `0` — fit the page to the window
- **‹ ›** / `←` `→` — previous / next page
- **Esporta PNG / SVG** — download the current page
