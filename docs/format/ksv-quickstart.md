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
spec/tools/ksv_quickstart.sh note
```

What to inspect first:

- `page-id`: page order, page UUIDs, and copied page hashes.
- `end-tag`: small global footer record.
- `media-info`: media manifest records; this uses `OnlyImages` because the
  `OnlyPens` media manifest is nearly empty.
- `page`: page header, layer tree, object entries, and embedded object headers.
- `note`: the whole `note.note` sequential structure — header, title/body Text
  blobs (via the imported `sdocx_text_wrapper`), and the field-flags-gated
  flex fields.

Only whole-ZIP-member specs are covered here, since the script's pattern is
"extract one member, point ksv at it". The remaining `spec/ksy/*.ksy` files
(`sdocx_object_header`, `sdocx_payload_geometry`, `sdocx_table_object`,
`sdocx_text_wrapper`, `sdocx_web_object`) each describe a slice at a
structurally-located offset *inside* a `.page` or `note.note` blob (an object
header, a shape/table/web body, …), not a standalone member — there's no
plain `unzip -p` target for them, so opening them in `ksv` needs the offset
pysdocx would compute first.

Names shown by `ksv` come from the `id` fields in `spec/ksy/*.ksy`. They are
project-chosen names, not official Samsung names. Some are intentionally generic
when the byte range is structurally decoded but its exact semantic meaning is
still unknown.
