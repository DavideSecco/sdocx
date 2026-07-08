# Kaitai Visualizer quickstart

These commands open small, known-good sample members in `ksv`. They extract the
ZIP member to `/tmp/sdocx-ksv` first because `.sdocx` files are ZIP containers,
while each `.ksy` describes one inner binary member.

Run from the repository root:

```bash
spec/tools/ksv_quickstart.sh page-id
spec/tools/ksv_quickstart.sh end-tag
spec/tools/ksv_quickstart.sh media-info
spec/tools/ksv_quickstart.sh page
```

What to inspect first:

- `page-id`: page order, page UUIDs, and copied page hashes.
- `end-tag`: small global footer record.
- `media-info`: media manifest records; this uses `OnlyImages` because the
  `OnlyPens` media manifest is nearly empty.
- `page`: page header, layer tree, object entries, and embedded object headers.

Names shown by `ksv` come from the `id` fields in `spec/ksy/*.ksy`. They are
project-chosen names, not official Samsung names. Some are intentionally generic
when the byte range is structurally decoded but its exact semantic meaning is
still unknown.
