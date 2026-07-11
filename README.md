# OpenSdocx

> **Open Samsung Notes, anywhere.**

OpenSdocx is a **standalone, multiplatform, open-source desktop app** that opens
Samsung Notes (`.sdocx`) files — faithfully, without a Samsung device or account,
and with your files never leaving your computer.

The goal is to be **the standard open-source way to open Samsung Notes**: there is
no working open-source viewer for these files on the desktop (Linux / Windows /
macOS), and OpenSdocx aims to fill that gap.

> **Status: in active development.** The app already opens a real `.sdocx` and
> renders it (strokes, images) with page navigation and document zoom; faithful
> rendering of every content type (shapes, grid/templates, typed text, tables,
> sticky notes, audio) plus export and text search are in progress. The living
> development plan is [`docs/app/README.md`](docs/app/README.md).

## Repository layout

- [`opensdocx/`](opensdocx/) — **the OpenSdocx app** (Tauri: a native Rust core +
  a web UI, one binary per OS).
- [`crates/`](crates/) — the Rust `.sdocx` parser/renderer the app is built on.
- [`pysdocx/`](pysdocx/) — Python reference implementation and reverse-engineering
  workbench; the correctness baseline the app's renderer is checked against.
- [`docs/format/`](docs/format/) + [`spec/`](spec/) — the reverse-engineered
  **format knowledge base** (narrative docs + machine-checked Kaitai specs).
- `samples/` — ground-truth corpus used to validate fidelity.

## Running the app (development)

Requires **Rust**, **Node.js 24 LTS**, and (on Linux) **`webkit2gtk-4.1`** +
**`gtk3`**. Use the npm version bundled with Node.js; if you use `nvm`, running
`nvm use` from the repository selects the supported Node.js release line.

```sh
npm --prefix opensdocx ci             # first time and after dependency changes
npm --prefix opensdocx run tauri dev  # build + launch the native window
```

Then click **Apri .sdocx** and pick a file from `samples/`.

## Credits

OpenSdocx builds on the Rust `.sdocx` decoder from
[twangodev/sdocx](https://github.com/twangodev/sdocx) (GPL-3.0), extended here with
substantial additional reverse-engineering of the format and a new rendering and
application layer.

## License

[GPL-3.0](LICENSE) — as required by the twangodev/sdocx core it builds on.
