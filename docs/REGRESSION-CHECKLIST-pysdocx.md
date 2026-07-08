# Regression Checklist — pysdocx

Use this after any `pysdocx` text-layout or page-template change, especially in `note.py`,
`page.py`, `render.py`, or `__main__.py`.

Always use the venv:

```bash
.venv/bin/python -m pysdocx text   <file>.sdocx ...
.venv/bin/python -m pysdocx render <file>.sdocx <outdir>
```

## 1. Squared Typed Text Baseline

File:

```text
samples/OnlyTextTypeWritten_squared_260703_013624.sdocx
```

Commands:

```bash
.venv/bin/python -m pysdocx text samples/OnlyTextTypeWritten_squared_260703_013624.sdocx --layout-debug
.venv/bin/python -m pysdocx render samples/OnlyTextTypeWritten_squared_260703_013624.sdocx /tmp/regression-squared
```

Expected:

- Page 1 uses the squared grid background.
- Typed text ends page 1 at `questo è heading 3`.
- Page 2 starts with `questo è heading 2`.
- Page 2 contains 3 text boxes:
  - one horizontal
  - one mildly rotated
  - one 90-degree rotated
- Page 3 is blank.

Known exception:

- Rotated text-box inner layout is still heuristic, even though the current squared GT check is
  visually close.
- The 90-degree text box should remain three logical columns/rows; the 16-degree box should wrap
  `2 righe inclinata` onto the third rendered line.

## 2. Typed Text Metadata

On the same squared sample, `python -m pysdocx text ...` should still show:

- decoded paragraph alignments
- indent levels
- numbered/bullet/todo list metadata
- heading/body styles
- font sizes
- text-box rich-text runs

Red flags:

- typed text missing entirely
- paragraph count collapsing
- page 2 text boxes disappearing
- `--layout-debug` failing to print lines for text boxes

## 3. Template Recognition

File:

```text
samples/OnlyTextTypeWritten_squared_260703_013624.sdocx
```

Expected:

- Template id 4 renders as a squared grid, not a plain white page.

## 4. Horizontal + Mildly Rotated Text Boxes

Same file, page 2.

Expected:

- horizontal text box remains a single logical line
- mildly rotated text box remains a short multi-line block
- neither should disappear or jump off-page

## 5. Manual Heuristic Audit

When editing the renderer, re-check that heuristic values are still clearly marked as such.

Current heuristic hotspots:

- `PARA_SPACE_UNIT`
- `TYPED_TEXT_BLANK_H`
- `TYPED_TEXT_PAGE_PAD`
- `_text_box_layout()` vertical-box wrap/anchor logic
- the “move whole styled run to next line” rule in `_render_rich_text`

## 6. Suggested Quick Sanity Commands

```bash
.venv/bin/python -m py_compile pysdocx/__main__.py pysdocx/render.py pysdocx/page.py pysdocx/note.py
.venv/bin/python spec/tools/analyze_sdocx2pdf_leads.py samples
git diff -- pysdocx/__main__.py pysdocx/render.py pysdocx/page.py pysdocx/note.py
```

If a change is meant to be diagnostic-only, verify that the rendered PNGs for the squared sample
do not unexpectedly move unrelated content.

Expected current `analyze_sdocx2pdf_leads.py` headline:

- `end_tag` variant gaps are all zero-hit on the current corpus.
- note title/body Common-like frame hits: 19/21 diagnostic surfaces.
- page text-box Common-like frame hits: 1/7.
- image/painting media-ref `u32` hits: 16/16.
- voice clips linked to `.m4a`: 2/2; page audio type-10 objects: 0.
