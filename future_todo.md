# Future TODO

## Current Checkpoint

- Branch baseline to resume from: `febc3cd feat(pysdocx): heading spacing and typed-text pagination`.
- Keep iterating in `pysdocx` first; do not port the rotated text-box behaviour to Rust yet.
- Current rotated text-box status:
  - Better than the old bbox-only wrap heuristic.
  - The renderer now uses decoded `frame_midpoints` from the first-class payload geometry wrapper when
    available on rotated boxes.
  - The 90-degree box in `samples/OnlyTextTypeWritten_squared_260703_013624.sdocx` now preserves the
    GT-like three-column wrap; keep treating it as provisional until more rotated samples exist.
  - Non-vertical rotated boxes use a small renderer-only inner-wrap inset (`18.0`) so the 16-degree
    sample wraps like the current GT.

## Known Open Risk

- File: `samples/OnlyTextTypeWritten_squared_260703_013624.sdocx`
- Page: 2
- Object: rotated in-page text boxes
- Symptom:
  - Current wrapping is visually calibrated against one GT sample, not fully decoded from file fields.
  - The 90-degree box should stay three logical rows; the 16-degree box should wrap `2 righe inclinata`
    onto the third row.
- Current heuristics involved:
  - `pysdocx/render.py:_text_box_layout` frame-midpoint projection + inner-wrap inset
  - The “move whole styled run to next line” rule in `_render_rich_text`
- Why this is still blocked:
  - We now have the rotated frame midpoints, but we still do not know whether Samsung stores any additional inner text padding or a logical text frame smaller than the visual frame.
  - We still do not know whether there are per-object layout fields beyond geometry + rich-text runs that affect wrapping.

## New Tooling Added

- `python -m pysdocx text ... --layout-debug`
  - Runs the current text-box layout heuristics.
  - Prints `text_off` and `object_off` for each text box.
  - Prints the chosen anchor, wrap width, line/blank height, and the wrapped logical lines.
  - Shows per-line segment/style boundaries, which is useful to spot run-boundary-induced wrapping artefacts.
- `python -m pysdocx text ... --json --layout-debug`
  - Includes `text_box_layout_debug` in the JSON output for each page.
- `docs/REGRESSION-CHECKLIST-pysdocx.md`
  - Compact sanity checklist for the squared typed-text sample and the current text-box state.
- `docs/TEXTBOX-ROTATION-RE-NOTES.md`
  - Object-level notes gathered from the existing `_squared` sample without creating new files.
- `docs/FORMAT-PROFILES.md` and `docs/FORMAT-COVERAGE-INVENTORY.json`
  - Current corpus-level family inventory for object headers, note.note profiles, and attachment bags.
- `python -m pysdocx inventory [paths...] [--json]`
  - Regenerates the machine-readable coverage/profile inventory from the current sample corpus.
  - Also surfaces conservative raw-tail RE diagnostics for preload preludes, pen-style tail blocks, and
    voice post `u32`/derived `u64` pairs.
  - Reports `payload_geometry_profiles` for the inserted-object wrapper:
    shape/image/text-box counts, point-count distribution, centroid checks, marker delta equations, and
    per-shape geometry roles.
- `python -m pysdocx objects ... --detail`
  - Prints decoded `payload_geometry` blocks where present (`L0`, `L1`, point count, marker deltas).
- `python -m pysdocx media-info <file> [--verify-hash] [--raw-tail]`
  - Prints the decoded `media/mediaInfo.dat` manifest, checks media existence, and can verify SHA-256
    against the archive members.
- `python -m pysdocx end-tag <file> [--raw]`
  - Prints the decoded `end_tag.bin` footer fields and the remaining raw middle/padding ranges.

## Reverse-Engineering Backlog

- Compare the raw object blobs for the 3 text boxes already present in `OnlyTextTypeWritten_squared_260703_013624.sdocx`:
  - horizontal
  - moderately rotated
  - 90-degree rotated
- Focus the comparison on fields that may encode:
  - logical text-box width independent of bbox
  - inner padding/insets
  - line direction or text flow orientation
  - per-object text layout metadata beyond style runs
- Do not spend time rediscovering the wrapper itself: it is now decoded as
  `obj["payload_geometry"]`, and text-box UTF-16 marker offset is covered by the `L1 + 172` equation.
- Use the new `--layout-debug` output as the “renderer hypothesis” side-by-side with the raw object offsets.

## Next Solid Tasks

- Separate decoded facts from heuristics even more explicitly in code comments and docs.
- Verify typed-text pagination + heading spacing on the existing samples again after any text-layout edits.
- Extend `pysdocx text --json` only with diagnostic data that is clearly marked as heuristic when it comes from the renderer.
- Add a compact regression checklist for:
  - squared grid template id 4
  - heading/body spacing
  - paginated typed text on page 2
  - horizontal text boxes
  - mildly rotated text boxes
- If time is limited, prefer diagnostics/object-level RE over more visual tuning of the rotated box.
- Treat `note.note` tail prelude/style/audio raw fields as structurally bounded but semantically
  unresolved. Current corpus shows useful distributions, but not enough isolated variation to promote
  the remaining raw fields to stable names.
- Treat the 11-byte `mediaInfo.dat` record tail similarly: manifest/index/name/SHA are decoded, while
  `tail_tag` and `time_candidate` remain diagnostics until isolated by new samples.
- Treat `end_tag.bin` middle fields similarly: size/format/modified/signature/footer constants are
  decoded, while the central raw region and old-sample timestamp unit differences need isolated samples.
- Treat current shape payload-geometry roles as corpus-backed, not universal: they cover every current
  shape sample, but new Samsung shape families may need new role names.

## Future Sample Campaign

- Not for now, but when ready, create a minimal “only text box” family:
  - same text box at `0 / 90 / 180 / 270` degrees
  - short vs long text
  - one line vs multi-line
  - plain vs bold/italic
- Goal:
  - isolate whether the rotated text-box bug is caused by missing geometry metadata or by wrapping logic alone.

## Deferred Audio Samples

- When motivation is there again, gather more `.sdocx` files with audio attachments.
- Why:
  - current corpus exposes two `voice_clip` records in `note.note`
  - current corpus still does NOT expose a trustworthy link from that record to the concrete audio attachment file/media index
  - additional audio-only / multi-audio / renamed-audio samples are the cleanest next step for that branch of RE
