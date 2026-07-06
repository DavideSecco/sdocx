# Conventions

Shared notation for the whole `docs/format/` tree, so individual pages stay DRY.

## Byte order and types

- **Endianness:** little-endian everywhere unless a page says otherwise.
- **Integer types:** `u8/u16/u32/u64` (unsigned), `s8/s16/s32/s64` (signed),
  `f32/f64` (IEEE-754). Widths are in bytes when written as `uN`/`sN` in prose
  and in Kaitai's `uN`/`sN`/`fN` in `.ksy` files.
- **Offsets** are byte offsets from the start of the relevant member/record
  unless stated. Object-blob offsets are measured from the object blob start;
  the common object header length is `105` (`OBJECT_BASE_HEADER_LEN`).
- **Strings:** typed text is UTF-16LE; manifest/signature strings are ASCII.
  Length-prefixed strings note their prefix type (`u16 char_len` etc.).
- **Timestamps:** epoch milliseconds unless a field is explicitly flagged as a
  candidate/other unit.

## Status legend

Every field, block, or behaviour is tagged with one of:

- **Decoded** — meaning is known and holds with **zero counterexamples** across
  the 13-sample corpus. Eligible for a named field in a `.ksy`.
- **Marker / Inferred** — located by a signature, consistency check, or payload
  marker; boundaries known, full field schema not yet.
- **Heuristic** — calibrated against ground-truth images, **not** decoded from
  the bytes. Never goes into a `.ksy`; lives in `heuristics.md`.
- **Unknown** — present in the bytes, not yet explained.

The promotion bar is deliberately high: prefer an honest **Unknown** island over
a speculative name. A field graduates from Unknown → Decoded only when a
corpus-wide check with no counterexamples backs it.

## The two layers

- **Formal spec** (`spec/ksy/*.ksy`): the *what* — byte layout, compiled to a
  real parser and validated field-by-field against `pysdocx`.
- **Narrative** (`docs/format/**`): the *why* and *how sure* — evidence,
  counts, uncertainty, unknowns, and anything (delta decompression,
  marker-scanning) that is procedural rather than declaratively parseable.

If the two ever disagree on a decoded field, the validation harness
(`spec/tools/`) fails — that is the intended tripwire.

## Corpus

The evidence base is the 13 `samples/*.sdocx` files. "13/13", "40/40", etc. in
these pages mean "held on that many of the relevant corpus objects/files with no
counterexample". No new samples are invented to make a claim; when the corpus
cannot isolate a field's meaning, it stays **Unknown**.
