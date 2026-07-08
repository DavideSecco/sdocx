# The Samsung Notes `.sdocx` format

A grounded, corpus-validated reverse-engineering reference for the Samsung Notes
/ S Pen `.sdocx` container.

This tree is the **narrative and evidence** layer: what each structure means,
how sure we are, and what is still unknown. The **formal, machine-checkable**
layer lives in [`spec/ksy/`](../../spec/ksy/) as Kaitai Struct definitions that
compile to real parsers and are validated field-by-field against the reference
`pysdocx` implementation. See [`../../spec/README.md`](../../spec/README.md).

> **Discipline (project rule):** a byte is only promoted to a named field when
> it holds with **zero counterexamples** across the 13-sample corpus. Anything
> calibrated against ground-truth images rather than decoded from the bytes is
> labelled **Heuristic** and lives in [`heuristics.md`](./heuristics.md), never
> in a `.ksy`. See [`00-conventions.md`](./00-conventions.md).

## The container

A `.sdocx` file is a ZIP archive. Its members:

| Member | Role | Doc | Spec |
|---|---|---|---|
| `pageIdInfo.dat` | True page order + per-page hashes | [`container/pageIdInfo.md`](./container/pageIdInfo.md) | [`sdocx_page_id_info.ksy`](../../spec/ksy/sdocx_page_id_info.ksy) ✅ |
| `note.note` | Typed text, tables, metadata, pen/voice flex fields | [`container/note-note/`](./container/note-note/) | [`sdocx_note.ksy`](../../spec/ksy/sdocx_note.ksy) ✅ (whole member) |
| `<uuid>.page` | Per-page layer/object tree (strokes, shapes, images, text) | [`container/page/`](./container/page/) | [`sdocx_page.ksy`](../../spec/ksy/sdocx_page.ksy) ✅ (header) |
| `media/mediaInfo.dat` | Media manifest (index, name, SHA-256) | [`container/mediaInfo.md`](./container/mediaInfo.md) | [`sdocx_media_info.ksy`](../../spec/ksy/sdocx_media_info.ksy) ✅ |
| `media/*` | Attachments: images, audio, sticky-memos | `container/attachments.md` *(todo)* | — |
| `end_tag.bin` | Fixed footer record | [`container/end-tag.md`](./container/end-tag.md) | [`sdocx_end_tag.ksy`](../../spec/ksy/sdocx_end_tag.ksy) ✅ |

✅ = decoded, documented, and corpus-validated. *(todo)* = knowledge exists in
the older round notes / `pysdocx`, not yet migrated into this tree.

## Status of this migration

This tree replaced the scattered round-by-round handoff notes, whose knowledge
has been absorbed here. The old `docs/*.md` round notes
(`FORMAT-COVERAGE-REPORT.md`, `FORMAT-PROFILES.md`, `OBJECT-HEADER-RE-NOTES.md`,
`HANDOFF-*.md`, `TEXTBOX-ROTATION-RE-NOTES.md`, `format-notes.md`) have been
removed to keep the docs low-noise. Still kept alongside this tree:

- `docs/FORMAT-COVERAGE-INVENTORY.json` — live generated artifact (regenerate
  with `pysdocx inventory samples --json`).
- `docs/REGRESSION-CHECKLIST-pysdocx.md` — operational render sanity checklist.

## Cross-cutting pages

- [`00-conventions.md`](./00-conventions.md) — types, byte-order, status legend.
- [`unknowns.md`](./unknowns.md) — every open question in one place.
- [`heuristics.md`](./heuristics.md) — render calibrations, explicitly not part
  of the decoded format.
