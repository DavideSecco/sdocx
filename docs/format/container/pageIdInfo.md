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
0       32    head_hash       Decoded (bytes) / Unknown (meaning)
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

### `head_hash` — 32 bytes @ 0
A document-level hash. Its bytes are read deterministically and are stable per
file, but the construction is not known, so only its presence and size are
promoted; the meaning is **Unknown**.

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

### `page_record.page_hash` — 32 bytes @ 74
An opaque per-page hash. **It is not the SHA-256 of the raw `.page` member**
(0/48 matches on the corpus), so it is some other digest or a hash over
different input. Bytes are decoded; meaning is **Unknown**.

## Unknown regions

- **`head_hash` construction** — 32 bytes, purpose unclear.
- **`page_hash` construction** — 32 bytes per page; not SHA-256 of the `.page`
  bytes. Candidate next step: try hashing canonicalised page content, or the
  page plus metadata, to see what reproduces these digests.
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
