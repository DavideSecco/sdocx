# Open questions

Every field/behaviour that is present in the bytes but **not yet decoded**, in
one place. Each stays Unknown deliberately: the 13-sample corpus bounds it
structurally but cannot isolate its meaning without samples that vary one
variable at a time. The discipline is "an honest Unknown over a speculative
name" ([conventions](./00-conventions.md)).

## `pageIdInfo.dat`
Both manifest hashes are decoded as **copies** — `head_hash = note.note[-32:]`
(13/13), `page_hash = the .page footer hash` (48/48). What remains open is one
shared question:
- **The 32-byte hash construction** stored at the tail of `note.note` and each
  `.page`. Negative results: no plain `sha256`/`sha3_256`/`blake2b` of the raw
  member reproduces it, and a full contiguous-range brute force on the smallest
  page finds nothing. Likely a canonical/serialized input or a keyed HMAC (the
  latter unrecoverable from files alone). Lower priority given that risk.

## `note.note`
- **`meta_flags`** bits other than `0x2000` (has-tables): `0x400`, `0x8000`, and
  `flags 0x8` show no clean feature against pages/images/shapes/sticky/template.
- **Tail records:** raw fields around `pen_preload_path`; preload param hints
  (`8;`, `14;`, `18;0;100;`…) — do not map 1:1 to pen tool names;
  `pen_style_tail.param` / `.raw_u32`; `tail_post_hash_u32` (matches
  `note.note[-4:]` on shifted samples → likely a copy, not a checksum);
  `voice_clip.post_u32` beyond the duration candidate; the meaning of the
  `tail_hash_block` hash itself.
- **Title object** inner schema (only the visible title text is scanned out).
- **Tables:** full block-level schema (borders, merges, column widths as stored
  fields); whether cell `kind` encodes a table style.
- **Rotated text-box** inner text padding / logical frame (currently
  [heuristic](./heuristics.md#rotated-text-box-wrapping)).

## `.page`
- **Object header `flags`** (u16): constant `0x1bf` on non-stroke objects; on
  strokes only bit `0x1` varies (an invariant, not a clean semantic).
- **`ext_block.seq` / `ext_block.counter`**: `seq` near-constant per note (not
  per-object, not monotonic); `counter` repeats / groups related-or-copied
  objects. No clean semantic.
- **`extra_key` trailing `u32 = 1`**: constant; flag-vs-count undecidable.
- **Raw-absolute-`f64` stroke variant**: observed on a couple of benchmark pages
  (absolute coordinate pairs, not deltas); neither known layout reads it.
- **Shape payloads:** complete formal schema for every variant; whether future
  shape families add payload-geometry point roles.
- **Drawing payload:** fuller object-level semantics.
- **Attachment placement:** structural page-object model when the object tree is
  empty (sticky/audio pages); recursive decode of nested sticky-note `.sdocx`.
- **Layer/content flags:** full semantics of all layer `content_flags` and
  `layer_flags` bits (boundaries known; not every bit meaning).

## `media/mediaInfo.dat`
- **Per-record `raw_tail`** (~11 bytes): `tail_tag` (1/3/5/20), the timestamp-like
  `time_candidate`, and the trailing marker byte.

## `end_tag.bin`
- **Middle raw regions** `[16,72)` (minus decoded islands) and `[96, footer)`.
- **Footer constants** (`02..02..ff*8`) are consistent but pattern-anchored, not
  offset-anchored — documented, not promoted.
- **Older-sample timestamp units**: `created_time_a/b` are ms-close (not exact) on
  the 3 older imports.

## Cross-file leads worth a targeted sample campaign
- A **"only text box at 0/90/180/270°"** family would isolate whether the rotated
  text-box wrap bug is missing geometry metadata or pure layout logic.
- More **audio** samples (multi-audio, renamed) would settle the
  `note.note` → `.m4a` linkage into a full schema.
