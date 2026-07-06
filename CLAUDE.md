# Working in this repo

Shared context for AI coding agents (Claude Code, Codex). Read this first; it is
the "how we work here" that the structured docs don't cover. Keep it current when
the working norms change.

## What this is

Reverse-engineered tooling for Samsung Notes `.sdocx` files (there is no working
open-source viewer on Linux). Upstream is the Rust workspace `twangodev/sdocx`;
active RE work happens on branch `feat/web-viewer`.

## Repo map

- `pysdocx/` — **the RE workbench.** A Python parser/renderer where all format
  decoding is prototyped and validated before anything is ported. This is where
  day-to-day work happens.
- `crates/` — the Rust workspace (`sdocx`, `sdocx-cli`, `sdocx-render`,
  `sdocx-wasm`) and `viewer/` — the shipped product. Lags pysdocx by design.
- `docs/format/` + `spec/` — **the format knowledge base** (see below).
- `samples/` — the 13-file ground-truth corpus. **Do not invent samples.** New
  ground-truth `.sdocx` files are made by the user, one variable at a time.
- `samsung-notes-format/` — the original minimal RE (`RESEARCH.md`); historical
  reference, not maintained.
- `notebooks/` — exploratory notebooks that import `pysdocx`.

## The format knowledge base — read before answering format questions

Two complementary layers; consult both, don't re-derive from raw bytes:

- **`docs/format/`** — narrative RE tree. Start at `docs/format/README.md`
  (container index), then `container/` → `note-note/` and `page/` sub-trees.
  `00-conventions.md` fixes the notation and the **Decoded / Marker / Heuristic /
  Unknown** legend. Open questions are consolidated in `unknowns.md`; render
  calibrations (NOT format facts) in `heuristics.md`.
- **`spec/ksy/`** — Kaitai Struct definitions for the 5 container members, each
  compiled to a parser and cross-checked field-by-field against `pysdocx` by
  `spec/tools/validate_*.py`. If a `.ksy` and `pysdocx` disagree, the validator
  fails — that is the point. See `spec/README.md` for the toolchain.
- `docs/FORMAT-COVERAGE-INVENTORY.json` — generated corpus inventory
  (`pysdocx inventory samples --json`). Don't hand-edit.

## Working discipline (important — this is the shared culture)

1. **pysdocx-first.** Decode and iterate in Python. Port to Rust only at
   checkpoints, not every round.
2. **Zero-counterexample promotion.** A byte becomes a named field only when it
   holds across the whole 13-sample corpus with no counterexample. Prefer an
   honest **Unknown** over a speculative name.
3. **Separate decoded facts from heuristics.** Anything calibrated against
   ground-truth images is a render heuristic, lives in `heuristics.md`, and never
   goes into a `.ksy`. Flag magic numbers/heuristics explicitly in code and prose.
4. **Never commit without the user's explicit OK.** Propose commits; let the user
   approve. When committing, use small logical commits.
5. **When you decode something new, extend all three layers together:** the
   `.ksy` + its `validate_*.py` + the relevant `docs/format/**` page. That keeps
   every advance both *proven* (validator) and *explained* (narrative).

## Running things

- **Python env is uv-managed and has no `pip`.** Use `uv pip install <pkg>`.
  Run everything with `.venv/bin/python` (system `python` lacks matplotlib etc.).
- **pysdocx regression tests** (there is no `pytest` in the venv):
  `.venv/bin/python -m unittest tests.test_pysdocx_regressions`
- **pysdocx CLI:** `.venv/bin/python -m pysdocx <cmd> <file>` where `<cmd>` is one
  of `dump stroke-table render text objects inventory media-info end-tag
  page-id-info`. Render/CLI need `.venv/bin/python`.
- **Rust:** `cargo nextest run --profile ci` (CI) or `cargo test`.
- **Kaitai validation** (the spec cross-check): install the toolchain once
  (`npm i kaitai-struct-compiler js-yaml` into a scratch dir; `uv pip install
  kaitaistruct`), then compile with `spec/tools/compile_ksy.js` and run the
  `spec/tools/validate_*.py`. Full recipe in `spec/README.md`. Generated parsers
  are scratch-only; never commit them.

## Notes

- The 13-sample corpus includes the user's personal `samples/Appunti vari_*` —
  keep it uncommitted/private. Same for `Interesting discussion.txt`.
- `future_todo.md` is a running backlog checkpoint; `unknowns.md` is the
  consolidated open-question list.
