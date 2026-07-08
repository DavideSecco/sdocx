# `pageIdInfo.dat`

The document's **page-order manifest**. The `.page` members of a `.sdocx`
archive are named by UUID and carry no intrinsic order, so this file is what
defines which page is first, second, and so on. It also stores an opaque
per-page hash.

- **Formal spec:** [`spec/ksy/sdocx_page_id_info.ksy`](../../../spec/ksy/sdocx_page_id_info.ksy)
  (validated corpus-wide — see [validation](#validation)).
- **Reference parser:** `parse_page_id_info` in [`pysdocx/container.py`](../../../pysdocx/container.py).
- **Conventions:** [`../00-conventions.md`](../00-conventions.md).

## At a glance

Little-endian. A fixed head, a page count, then fixed-size records — fully
decoded, zero counterexamples across the corpus (48 records over 13 files).

```
offset  size  field           status
0       32    head_hash       Decoded   copy of sha256(note.note[:-32])
32      2     page_count      Decoded
34      ...   page_record[]   Decoded   page_count x 106 bytes
```

Each `page_record` is exactly 106 bytes with no padding:

```
offset  size  field        status
0       2     uuid_len     Decoded   always 36
2       72    uuid         Decoded   UTF-16LE page UUID (uuid_len x 2)
74      32    page_hash    Decoded (bytes) / Unknown (meaning)
```

## Decoded fields

### `head_hash` — 32 bytes @ 0 — Decoded
A document-level hash copied from `note.note`: it equals **`note.note`'s trailing
32 bytes** (`head_hash == note.note[-32:]`) on **13/13** samples, and that
trailing value is **`sha256(note.note[:-32])`** on **13/13**. So
`pageIdInfo.dat` is a manifest mirror, not the place where the digest is
computed.

### `page_count` — `u16` @ 32
Number of `page_record`s that follow. The list order **is** the document's page
order: index *i* here is page *i*. This is the field the renderer relies on to
place pages, rather than the archive's member order.

### `page_record.uuid_len` — `u16` @ 0
UTF-16 character count of the UUID. Always `36` on the corpus (a canonical
`xxxxxxxx-xxxx-...` UUID string).

### `page_record.uuid` — UTF-16LE @ 2
The page UUID, matching a `<uuid>.page` member in the archive. This is the link
from page order to page content.

### `page_record.page_hash` — 32 bytes @ 74 — Decoded (source found)
This is **not a digest computed over the raw `.page` member** (0/48 SHA-256
matches). It is a **copy of the page's own stored footer hash**: every `.page`
file ends with a 32-byte content hash immediately followed by the ASCII
signature `Page for SAMSUNG S-Pen SDK`, and this manifest field is that exact
hash, mirrored. Confirmed on **48/48** pages (`page_hash == .page[-58:-26]`, and
the test gate cross-checks the two per page). See
[the page footer](./page/README.md#page-footer--decoded). How the page itself
computes that 32-byte hash is still Unknown, but the manifest↔page linkage is
decoded.

## Unknown regions

`head_hash` is fully explained: `head_hash = note.note[-32:] =
sha256(note.note[:-32])` on 13/13.

What remains open is the **page** hash construction. `page_hash` is decoded as a
copy of each `.page` footer hash, but the footer hash itself is not reproduced by
plain `sha256`/`sha3_256`/`blake2b` of the raw page member, and a full
contiguous-range brute force over the smallest page found no match. It likely
uses a canonical/serialized input or a keyed construction.
- There is **no trailing data**: records tile the file exactly
  (`valid_size` true on 13/13), so there is no unexplained tail here.

## Validation

```bash
KSC_GEN=<scratch>/gen .venv/bin/python spec/tools/validate_page_id_info.py
# -> 13 matched, 0 mismatched, out of 13 parsed
```

The check compares `head_hash`, `page_count`, and every record's `uuid` and
`page_hash` against the reference `pysdocx` parser. See
[`../../../spec/README.md`](../../../spec/README.md) for the toolchain.
