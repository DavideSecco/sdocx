meta:
  id: sdocx_image_object
  title: Samsung Notes .sdocx imported-image crop flex
  application: Samsung Notes / S Pen SDK
  endian: le
  license: CC0-1.0
doc: |
  The crop flex of an imported-image placement record, fed the object bytes
  starting at the image's media-reference marker (`06 00 3e 00 00 00 02 00`,
  followed by the u32 media archive index). Everything before it — the common
  object header, the payload-geometry wrapper, the `01 00 04 20` placement marker
  + 4xf64 bbox + edge-midpoint geometry — is marker-scanned/decoded elsewhere
  (docs/format/container/page/object-types.md); this models only the crop, the
  newly decoded field.

  A field-flag byte's `0x40` bit marks a cropped image; when set, a 4xf64 rect
  gives where the FULL (uncropped) image would sit on the page (its aspect equals
  the source image's), and the placement bbox is the cropped window inside it —
  so the visible source sub-rect is that bbox normalized into this rect. Offsets
  are relative to the media reference and calibrated on the two cropped images in
  ImagesAllTrasnsformations (a page-object crop, aspect 3.076, and a note.note
  inline crop, aspect 2.786).
seq:
  - id: media_ref_marker
    contents: [0x06, 0x00, 0x3e, 0x00, 0x00, 0x00, 0x02, 0x00]
  - id: media_index
    type: u4
    doc: Global media archive index (the `<index>@` prefix of the media member).
instances:
  crop_flag:
    pos: 69
    type: u1
    doc: |
      Crop field-flag byte, at media-reference offset 12 + 57. Bit 0x40 marks a
      cropped image (65 = 0x41 when cropped, 17 = 0x11 when full).
  is_cropped:
    value: (crop_flag & 0x40) != 0
  crop_full_rect:
    pos: 102
    type: rect
    if: is_cropped
    doc: |
      The full (uncropped) image's page placement rectangle (media-reference
      offset 12 + 90). Present only when cropped.
types:
  rect:
    seq:
      - id: x0
        type: f8
      - id: y0
        type: f8
      - id: x1
        type: f8
      - id: y1
        type: f8
