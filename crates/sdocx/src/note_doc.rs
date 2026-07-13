//! Byte-exact `note.note` structural decode: the `text_core::Common` rich-text
//! frame, the `ObjectBase -> ShapeBase -> Shape -> Text` wrapper around it, and
//! the type-22 table inline object.
//!
//! Straight port of pysdocx's `pysdocx/note_doc.py` (`parse_common_frame`,
//! `find_common_frames`, `parse_text_wrapper`, the note-doc header, and
//! `parse_table_object` with its `_parse_table_*` helpers) — keep the two in
//! lockstep when either side changes.
//!
//! The Text/Shape wrapper (`parse_text_wrapper`) walks the four inclusive
//! `ObjectHeader` frames and reaches Common through Shape's decoded flex offset,
//! so the note body typed text (`note_body_rich_text`) and raw page text boxes
//! (`text_wrapper_rich_text`) are decoded structurally instead of by the legacy
//! marker/TLV scan in `container::parse_note_text` / `page::text_box_text`.
//! Validated against pysdocx `parse_text_wrapper` by the `wrapper_parity` gate.
//!
//! Unlike the legacy marker-scan table reader (`container::parse_tables`), the
//! table decode parses the whole object sequentially and byte-exactly: sized
//! wrapper/midpoint/outline records, column widths, length-chained rows and
//! cells with page-coordinate bboxes, per-cell fill + nested Common frame, and
//! the style tail (outer/grid border blocks, per-column width constraints, theme
//! fill). Validated against pysdocx `note_doc_tables` by `tests/note_tables.rs`.

use crate::types::{
    Alignment, BoundingBox, Color, ColorRun, FontSizeRun, ListItem, NoteTable, NoteTableCell,
    ParagraphInfo, ParagraphStyle, Point, RichTextBox, RichTextRun, TableBorder, TableCellSpan,
};

/// Inline objects appear in Common frames only from this format version on
/// (sdocx2pdf gate; corpus versions are 4000/5400, both above it).
const INLINE_OBJECTS_MIN_FORMAT: u32 = 2035;
/// u32 span_type + u32 start + u32 end + u32 interval_type.
const SPAN_BASE_SIZE: usize = 16;
/// u32 paragraph_type + u32 start + u32 end.
const PARAGRAPH_BASE_SIZE: usize = 12;
const TABLE_OBJECT_TYPE: u32 = 22;

/// `01 00 02 00 00` — serialization preamble (Marker).
const T5: [u8; 5] = [0x01, 0x00, 0x02, 0x00, 0x00];
/// `u32 0` + T5.
const PRE9: [u8; 9] = [0, 0, 0, 0, 0x01, 0x00, 0x02, 0x00, 0x00];
/// `0f 00 00 00 02 00 00 00 00 00` + T5 — the per-cell record terminator.
const TOKEN15: [u8; 15] = [
    0x0f, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00, 0x00,
];

type R<T> = Result<T, &'static str>;

fn ensure(cond: bool, msg: &'static str) -> R<()> {
    if cond { Ok(()) } else { Err(msg) }
}

/// Bounds-checked little-endian cursor over a byte window (pysdocx `_Cur`).
struct Cur<'a> {
    data: &'a [u8],
    pos: usize,
    end: usize,
}

impl<'a> Cur<'a> {
    fn new(data: &'a [u8], pos: usize, end: usize) -> Self {
        Cur { data, pos, end }
    }

    fn need(&self, n: usize) -> R<()> {
        ensure(self.pos + n <= self.end, "cursor overrun")
    }

    fn bytes(&mut self, n: usize) -> R<&'a [u8]> {
        self.need(n)?;
        let out = &self.data[self.pos..self.pos + n];
        self.pos += n;
        Ok(out)
    }

    fn u8(&mut self) -> R<u8> {
        Ok(self.bytes(1)?[0])
    }
    fn u16(&mut self) -> R<u16> {
        Ok(u16::from_le_bytes(self.bytes(2)?.try_into().unwrap()))
    }
    fn u32(&mut self) -> R<u32> {
        Ok(u32::from_le_bytes(self.bytes(4)?.try_into().unwrap()))
    }
    fn i64(&mut self) -> R<i64> {
        Ok(i64::from_le_bytes(self.bytes(8)?.try_into().unwrap()))
    }
    fn f32(&mut self) -> R<f32> {
        Ok(f32::from_le_bytes(self.bytes(4)?.try_into().unwrap()))
    }
    fn f64(&mut self) -> R<f64> {
        Ok(f64::from_le_bytes(self.bytes(8)?.try_into().unwrap()))
    }

    /// A `[u16 count]` UTF-16LE string.
    fn short_utf16(&mut self) -> R<String> {
        let n = self.u16()? as usize;
        self.utf16(n)
    }

    fn utf16(&mut self, char_count: usize) -> R<String> {
        let raw = self.bytes(2 * char_count)?;
        let units: Vec<u16> = raw
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .collect();
        String::from_utf16(&units).map_err(|_| "invalid utf-16")
    }

    /// `[u8 n_bytes][n-byte little-endian bits]`; returns the integer value.
    fn bitfield(&mut self) -> R<u32> {
        let n = self.u8()? as usize;
        ensure(n <= 4, "bitfield size > 4")?;
        let raw = self.bytes(n)?;
        let mut v = 0u32;
        for (i, b) in raw.iter().enumerate() {
            v |= (*b as u32) << (8 * i);
        }
        Ok(v)
    }

    /// A sub-window of `size` bytes at the current position (advances self).
    fn sub(&mut self, size: usize) -> R<Cur<'a>> {
        self.need(size)?;
        let child = Cur::new(self.data, self.pos, self.pos + size);
        self.pos += size;
        Ok(child)
    }

    fn remaining(&self) -> usize {
        self.end - self.pos
    }
}

fn ensure_eof(cur: &Cur, msg: &'static str) -> R<()> {
    ensure(cur.remaining() == 0, msg)
}

fn rect(cur: &mut Cur) -> R<BoundingBox> {
    Ok(BoundingBox {
        x_min: cur.f64()?,
        y_min: cur.f64()?,
        x_max: cur.f64()?,
        y_max: cur.f64()?,
    })
}

// --- text_core::Common frame ----------------------------------------------

/// One decoded span record within a Common frame.
struct FrameSpan {
    span_type: u32,
    start: u32,
    end: u32,
    interval_type: u32,
    /// First u32 of the span payload (colour ARGB / f32 bits / bool), 0 if empty.
    value: u32,
}

/// One type-22 inline object entry inside a Common frame.
struct InlineObject {
    obj_size: usize,
    object_type: u32,
    /// Offset of the object body within the blob passed to `parse_common_frame`.
    body_off: usize,
}

/// One decoded structural paragraph record within a Common frame (pysdocx
/// `parse_common_frame`'s `paragraphs`). `start`/`end` index paragraphs
/// (`text.split('\n')`), not characters. `extra` is the raw `size - 12`
/// payload; see `structural_paragraphs` for how `paragraph_type` gates its
/// interpretation.
struct FrameParagraph {
    paragraph_type: u32,
    start: u32,
    end: u32,
    extra: Vec<u8>,
}

/// A parsed `text_core::Common` exclusive frame.
struct CommonFrame {
    frame_size: usize,
    text: String,
    spans: Vec<FrameSpan>,
    paragraphs: Vec<FrameParagraph>,
    inline_objects: Vec<InlineObject>,
}

/// Parse one Common frame at `off` inside `blob` (pysdocx `parse_common_frame`).
fn parse_common_frame(blob: &[u8], off: usize, format_version: u32) -> R<CommonFrame> {
    let mut cur = Cur::new(blob, off, blob.len());
    let frame_size = cur.u32()? as usize;
    if frame_size < 4 || off + 4 + frame_size > blob.len() {
        return Err("common frame size out of range");
    }
    let mut win = cur.sub(frame_size)?;

    let char_count = win.u32()? as usize;
    if char_count > win.remaining() / 2 {
        return Err("common text char count too large");
    }
    let text = win.utf16(char_count)?;

    let span_count = win.u32()? as usize;
    if span_count > win.remaining() / (2 + SPAN_BASE_SIZE) + 1 {
        return Err("span count too large");
    }
    let mut spans = Vec::with_capacity(span_count);
    for _ in 0..span_count {
        let size = win.u16()? as usize;
        ensure(size >= SPAN_BASE_SIZE, "span record too small")?;
        let span_type = win.u32()?;
        let start = win.u32()?;
        let end = win.u32()?;
        let interval_type = win.u32()?;
        let extra = win.bytes(size - SPAN_BASE_SIZE)?;
        let value = if extra.len() >= 4 {
            u32::from_le_bytes(extra[0..4].try_into().unwrap())
        } else {
            0
        };
        spans.push(FrameSpan { span_type, start, end, interval_type, value });
    }

    let paragraph_count = win.u32()? as usize;
    if paragraph_count > win.remaining() / (2 + PARAGRAPH_BASE_SIZE) + 1 {
        return Err("paragraph count too large");
    }
    let mut paragraphs = Vec::with_capacity(paragraph_count);
    for _ in 0..paragraph_count {
        let size = win.u16()? as usize;
        ensure(size >= PARAGRAPH_BASE_SIZE, "paragraph record too small")?;
        let paragraph_type = win.u32()?;
        let start = win.u32()?;
        let end = win.u32()?;
        let extra = win.bytes(size - PARAGRAPH_BASE_SIZE)?.to_vec();
        paragraphs.push(FrameParagraph { paragraph_type, start, end, extra });
    }

    let _margins = [win.f32()?, win.f32()?, win.f32()?, win.f32()?];
    let gravity = win.u8()?;
    ensure(gravity <= 2, "gravity not in 0..2")?;

    let section_count = win.u16()? as usize;
    if section_count > win.remaining() / 8 {
        return Err("section count too large");
    }
    for _ in 0..section_count {
        win.u32()?;
        win.u32()?;
    }

    let mut inline_objects = Vec::new();
    if format_version >= INLINE_OBJECTS_MIN_FORMAT {
        let inline_present = win.u32()?;
        let _inline_zero = win.u32()?;
        if inline_present != 0 {
            let obj_count = win.u32()? as usize;
            if obj_count > 4096 {
                return Err("inline object count implausible");
            }
            for _ in 0..obj_count {
                let obj_frame = win.u32()? as usize;
                let mut obj_win = win.sub(obj_frame)?;
                let obj_size = obj_win.u32()? as usize;
                let object_type = obj_win.u32()?;
                let body_off = obj_win.pos;
                obj_win.bytes(obj_size)?;
                let _position = obj_win.u32()?;
                // trailing 8 bytes of Unknown semantics are left unconsumed here.
                inline_objects.push(InlineObject { obj_size, object_type, body_off });
            }
        }
    }

    Ok(CommonFrame { frame_size, text, spans, paragraphs, inline_objects })
}

/// All offsets in `blob` where a complete Common frame parses cleanly (pysdocx
/// `find_common_frames`). The Text/Shape wrapper isn't modeled, so frames are
/// located by exhaustive offset scan; the exact-size constraint makes false
/// positives rare (on the corpus this finds the body frame + one per cell).
fn find_common_frames(blob: &[u8], format_version: u32) -> Vec<(usize, CommonFrame)> {
    let mut frames = Vec::new();
    if blob.len() < 8 {
        return frames;
    }
    for off in 0..blob.len() - 8 {
        if let Ok(frame) = parse_common_frame(blob, off, format_version) {
            frames.push((off, frame));
        }
    }
    frames
}

// --- Text/Shape wrapper ---------------------------------------------------
//
// The title/body Text blobs and raw type-2 page text boxes share one inclusive
// inheritance chain `ObjectBase(0) -> ShapeBase(6) -> Shape(7) -> Text(2)`.
// Every class is an inclusive-length `ObjectHeader` frame; Shape's decoded flex
// offset lands directly on `text_core::Common`, so the rich-text frame is
// reached structurally instead of by marker/byte scan (pysdocx
// `parse_text_wrapper`). Straight port of `pysdocx/note_doc.py`.

/// The shared inclusive `ObjectHeader` frame used by every class in the
/// inheritance chain (pysdocx `_parse_object_frame_header`). Distinct from
/// `page.rs`'s `parse_object_header`, which decodes only the fields stroke/image
/// consumers need. `flex_off` is absolute (frame start + `flex_offset`).
// `off`/`size` are part of the decoded RE record and asserted by the parity
// gate, but the byte-exact parse itself doesn't re-read them.
#[allow(dead_code)]
struct ObjectFrameHeader {
    off: usize,
    size: usize,
    end: usize,
    field_flags: u32,
    flex_off: Option<usize>,
    header_end: usize,
}

fn parse_object_frame_header(blob: &[u8], off: usize, expected_type: u16) -> R<ObjectFrameHeader> {
    let mut cur = Cur::new(blob, off, blob.len());
    let size = cur.u32()? as usize;
    if size < 12 || off + size > blob.len() {
        return Err("object frame size out of range");
    }
    if cur.u16()? != expected_type {
        return Err("object frame type mismatch");
    }
    let flex_offset = cur.u32()? as usize;
    let _property_flags = cur.bitfield()?;
    let field_flags = cur.bitfield()?;
    let header_end = cur.pos;
    if flex_offset != 0 && !((header_end - off) <= flex_offset && flex_offset <= size) {
        return Err("object flex offset outside frame header/size");
    }
    Ok(ObjectFrameHeader {
        off,
        size,
        end: off + size,
        field_flags,
        flex_off: (flex_offset != 0).then_some(off + flex_offset),
        header_end,
    })
}

fn read_f32(blob: &[u8], p: usize) -> R<f32> {
    let b = blob.get(p..p + 4).ok_or("f32 out of range")?;
    Ok(f32::from_le_bytes(b.try_into().unwrap()))
}

fn read_f64(blob: &[u8], p: usize) -> R<f64> {
    let b = blob.get(p..p + 8).ok_or("f64 out of range")?;
    Ok(f64::from_le_bytes(b.try_into().unwrap()))
}

/// Format version is the first fixed ObjectBase field after its header
/// (pysdocx `base_format_version`).
fn base_format_version(blob: &[u8], base: &ObjectFrameHeader) -> R<u32> {
    let b = blob.get(base.header_end..base.header_end + 4).ok_or("format version out of range")?;
    Ok(u32::from_le_bytes(b.try_into().unwrap()))
}

/// A parsed `Text -> Shape -> ShapeBase -> ObjectBase` wrapper. Mirrors the
/// pysdocx `parse_text_wrapper` dict: most fields are the decoded RE record,
/// proven byte-exact by the parse asserts and checked by the parity gate; only
/// `common` feeds the rich-text consumers, so the rest read as dead outside
/// tests.
#[allow(dead_code)]
struct TextWrapper {
    base: ObjectFrameHeader,
    base_angle: Option<f32>,
    base_pivot: Option<(f64, f64)>,
    shape_base: ObjectFrameHeader,
    shape: ObjectFrameHeader,
    shape_type: u32,
    original_rect: [f64; 4],
    original_angle: f32,
    path_raw: Vec<u8>,
    control_points: Vec<(f64, f64)>,
    common: Option<CommonFrame>,
    shape_field_11_f32: Option<f32>,
    ellipsis_type: Option<u8>,
    text_auto_fit_type: Option<u8>,
    text: ObjectFrameHeader,
    border_colour: Option<[u8; 4]>,
    border_width: Option<f32>,
    border_type: Option<u16>,
    trailing_len: usize,
}

/// Parse a complete Text wrapper at `blob[off..]` (pysdocx `parse_text_wrapper`).
/// The Common frame is reached through Shape's decoded flex offset; no marker or
/// exhaustive byte scan is used. Any deviation returns `Err`.
fn parse_text_wrapper(blob: &[u8], off: usize) -> R<TextWrapper> {
    let base = parse_object_frame_header(blob, off, 0)?;
    // ObjectBase's individual fixed fields are decoded by page.rs; here we only
    // surface the two flex fields that explain the wrapper's size variants
    // (rotation angle and pivot). Serialized in bit order.
    let mut base_angle = None;
    let mut base_pivot = None;
    if let Some(flex) = base.flex_off {
        let mut p = flex;
        let flags = base.field_flags;
        let supported = (1 << 0) | (1 << 13) | (1 << 14) | (1 << 18);
        ensure(flags & !supported == 0, "text ObjectBase unhandled fields")?;
        if flags & (1 << 0) != 0 {
            base_angle = Some(read_f32(blob, p)?);
            p += 4;
        }
        if flags & (1 << 13) != 0 {
            p += 8; // append_time_us
        }
        if flags & (1 << 14) != 0 {
            p += 8; // owner page width/height
        }
        if flags & (1 << 18) != 0 {
            base_pivot = Some((read_f64(blob, p)?, read_f64(blob, p + 8)?));
            p += 16;
        }
        ensure(p == base.end, "ObjectBase fields end != frame end")?;
    }

    let shape_base = parse_object_frame_header(blob, base.end, 6)?;
    let shape = parse_object_frame_header(blob, shape_base.end, 7)?;

    let mut cur = Cur::new(blob, shape.header_end, shape.end);
    let shape_type = cur.u32()?;
    let original_rect = [cur.f64()?, cur.f64()?, cur.f64()?, cur.f64()?];
    let original_angle = cur.f32()?;
    let path_size = cur.u32()? as usize;
    let path_raw = cur.bytes(path_size)?.to_vec();
    let control_count = cur.u8()? as usize;
    let mut control_points = Vec::with_capacity(control_count);
    for _ in 0..control_count {
        control_points.push((cur.f64()?, cur.f64()?));
    }
    let shape_flex = shape.flex_off.ok_or("Shape has no flex offset")?;
    ensure(cur.pos == shape_flex, "Shape fixed fields end != flex offset")?;

    let flags = shape.field_flags;
    let supported = (1 << 0) | (1 << 11) | (1 << 12) | (1 << 13);
    ensure(flags & !supported == 0, "Text Shape unhandled fields")?;
    let mut common = None;
    if flags & 1 != 0 {
        let fmt = base_format_version(blob, &base)?;
        let frame = parse_common_frame(blob, cur.pos, fmt)?;
        cur.pos += 4 + frame.frame_size;
        common = Some(frame);
    }
    let shape_field_11_f32 = if flags & (1 << 11) != 0 { Some(cur.f32()?) } else { None };
    let ellipsis_type = if flags & (1 << 12) != 0 { Some(cur.u8()?) } else { None };
    let text_auto_fit_type = if flags & (1 << 13) != 0 { Some(cur.u8()?) } else { None };
    ensure_eof(&cur, "Shape Text wrapper")?;

    let text = parse_object_frame_header(blob, shape.end, 2)?;
    if let Some(flex) = text.flex_off {
        ensure(text.header_end == flex, "Text frame has unexpected fixed fields")?;
    }
    let mut cur = Cur::new(blob, text.flex_off.unwrap_or(text.header_end), text.end);
    let text_flags = text.field_flags;
    ensure(text_flags & !0x0e == 0, "Text unhandled fields")?;
    let border_colour = if text_flags & 2 != 0 {
        Some(<[u8; 4]>::try_from(cur.bytes(4)?).unwrap())
    } else {
        None
    };
    let border_width = if text_flags & 4 != 0 { Some(cur.f32()?) } else { None };
    let border_type = if text_flags & 8 != 0 { Some(cur.u16()?) } else { None };
    ensure_eof(&cur, "Text frame")?;

    let trailing_len = blob.len() - text.end;
    if trailing_len != 0 && trailing_len != 32 {
        return Err("Text wrapper leaves unexpected trailing bytes");
    }

    Ok(TextWrapper {
        base,
        base_angle,
        base_pivot,
        shape_base,
        shape,
        shape_type,
        original_rect,
        original_angle,
        path_raw,
        control_points,
        common,
        shape_field_11_f32,
        ellipsis_type,
        text_auto_fit_type,
        text,
        border_colour,
        border_width,
        border_type,
        trailing_len,
    })
}

/// The rich-text projection of a Text wrapper: the Common frame's spans mapped
/// to style/colour/font runs (pysdocx `page._text_box_rich_text` structural
/// branch). Shared by page text boxes and the note body typed text.
pub(crate) struct WrapperRichText {
    pub text: String,
    pub runs: Vec<RichTextRun>,
    pub colors: Vec<ColorRun>,
    pub highlights: Vec<ColorRun>,
    pub font_sizes: Vec<FontSizeRun>,
    pub paragraphs: Vec<ParagraphInfo>,
}

fn u32_at(b: &[u8], off: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(off..off + 4)?.try_into().ok()?))
}

fn f32_at(b: &[u8], off: usize) -> Option<f32> {
    u32_at(b, off).map(f32::from_bits)
}

/// Decode a Common frame's structural `paragraphs` records into per-paragraph
/// layout metadata, aligned index-for-index with `frame.text.split('\n')`
/// (straight port of pysdocx `note_doc.common_frame_paragraphs` — see its
/// docstring for the `paragraph_type` -> payload-field mapping, validated
/// zero-counterexample against the legacy TLV marker scan on the whole
/// corpus).
fn structural_paragraphs(frame: &CommonFrame) -> Vec<ParagraphInfo> {
    let paragraph_count = frame.text.split('\n').count();
    let mut paragraphs = vec![ParagraphInfo::default(); paragraph_count];
    for rec in &frame.paragraphs {
        let (start, end) = (rec.start as usize, rec.end as usize);
        if !(start < end && end <= paragraph_count) {
            continue;
        }
        let extra = &rec.extra;
        for p in &mut paragraphs[start..end] {
            match rec.paragraph_type {
                2 => {
                    if let (Some(value), Some(enabled)) = (u32_at(extra, 0), u32_at(extra, 4))
                        && enabled != 0
                    {
                        p.indent = value;
                    }
                }
                3 => {
                    if let Some(value) = u32_at(extra, 0) {
                        p.alignment = match value {
                            0 => Alignment::Left,
                            1 => Alignment::Right,
                            2 => Alignment::Center,
                            _ => p.alignment,
                        };
                    }
                }
                4 => {
                    if let Some(spacing) = f32_at(extra, 4)
                        && spacing.is_finite()
                        && (0.5..=4.0).contains(&spacing)
                    {
                        p.line_spacing = Some(spacing);
                    }
                }
                5 => {
                    if let (Some(kind), Some(value), Some(enabled)) =
                        (u32_at(extra, 0), u32_at(extra, 4), u32_at(extra, 12))
                        && enabled != 0
                    {
                        p.list = match kind {
                            4 => Some(ListItem::Numbered { number: value }),
                            8 => Some(ListItem::Bullet),
                            2 => Some(ListItem::Todo { checked: value != 0 }),
                            _ => p.list,
                        };
                    }
                }
                8 => {
                    if let Some(value) = f32_at(extra, 0)
                        && value.is_finite()
                        && (0.0..=200.0).contains(&value)
                    {
                        p.space_before = value;
                    }
                }
                9 => {
                    if let Some(value) = f32_at(extra, 0)
                        && value.is_finite()
                        && (0.0..=200.0).contains(&value)
                    {
                        p.space_after = value;
                    }
                }
                10 => {
                    if let Some(value) = u32_at(extra, 0) {
                        p.style = match value {
                            0 => Some(ParagraphStyle::Heading1),
                            1 => Some(ParagraphStyle::Heading2),
                            2 => Some(ParagraphStyle::Heading3),
                            3 => Some(ParagraphStyle::Body1),
                            _ => p.style,
                        };
                    }
                }
                _ => {}
            }
        }
    }
    paragraphs
}

fn common_frame_rich_text(frame: &CommonFrame) -> Option<WrapperRichText> {
    let text: String = frame.text.trim_end_matches(['\0', '\n']).to_string();
    if text.trim().is_empty() {
        return None;
    }
    let text_len = text.chars().count();
    let mut runs = Vec::new();
    let mut colors = Vec::new();
    let mut highlights = Vec::new();
    let mut font_sizes = Vec::new();
    for span in &frame.spans {
        let start = span.start as usize;
        let end = (span.end as usize).min(text_len);
        if start >= end {
            continue;
        }
        let value = span.value;
        match span.span_type {
            5 | 6 | 7 | 20 if value != 0 => runs.push(RichTextRun {
                start,
                end,
                bold: span.span_type == 5,
                italic: span.span_type == 6,
                underline: span.span_type == 7,
                strikethrough: span.span_type == 20,
            }),
            1 | 17 if value >> 24 == 0xFF => {
                let row = ColorRun {
                    start,
                    end,
                    color: Color { r: (value >> 16) as u8, g: (value >> 8) as u8, b: value as u8 },
                };
                if span.span_type == 1 {
                    colors.push(row);
                } else {
                    highlights.push(row);
                }
            }
            3 => {
                let size = f32::from_bits(value);
                if size.is_finite() && (4.0..=200.0).contains(&size) {
                    font_sizes.push(FontSizeRun { start, end, size });
                }
            }
            _ => {}
        }
    }
    let paragraphs = structural_paragraphs(frame);
    Some(WrapperRichText { text, runs, colors, highlights, font_sizes, paragraphs })
}

/// Decode a raw type-2 page text-box blob through the structural wrapper and
/// project it to rich text. `None` when the blob isn't a well-formed wrapper
/// (caller falls back to the legacy marker scan) or carries no visible text.
pub(crate) fn text_wrapper_rich_text(blob: &[u8]) -> Option<WrapperRichText> {
    let wrapper = parse_text_wrapper(blob, 0).ok()?;
    common_frame_rich_text(wrapper.common.as_ref()?)
}

/// The note body's typed text, reached through the ObjectBase/ShapeBase/Shape
/// chain of the body Text blob (pysdocx `note_doc_common_frames` body +
/// `_text_box_rich_text` projection).
pub(crate) fn note_body_rich_text(note: &[u8]) -> Option<WrapperRichText> {
    let header = parse_note_doc_header(note).ok()?;
    let body_end = header.body_off + header.body_size;
    let body = note.get(header.body_off..body_end)?;
    text_wrapper_rich_text(body)
}

/// Build a `RichTextBox` from a wrapper's rich-text projection and the object's
/// placement (bbox / rotation / frame midpoints). Shared by the page text-box
/// and note-body paths, which differ only in how they obtain the placement.
pub(crate) fn wrapper_rich_text_box(
    rt: WrapperRichText,
    bbox: BoundingBox,
    rotation_degrees: Option<f64>,
    frame_midpoints: Option<[Point; 4]>,
) -> RichTextBox {
    RichTextBox {
        bbox,
        rotation_degrees,
        text: rt.text,
        color: rt.colors.first().map(|c| c.color),
        highlight_color: rt.highlights.first().map(|c| c.color),
        underline: rt.runs.iter().any(|r| r.underline),
        font_size: rt.font_sizes.first().map(|f| f.size),
        runs: rt.runs,
        colors: rt.colors,
        highlights: rt.highlights,
        font_sizes: rt.font_sizes,
        frame_midpoints,
        paragraphs: rt.paragraphs,
    }
}

// --- note-doc header ------------------------------------------------------

/// The fixed head of `note.note` up to the body blob (pysdocx `parse_note_doc`,
/// truncated at the fields the table decode needs).
struct NoteHeader {
    format_version: u32,
    body_off: usize,
    body_size: usize,
}

fn parse_note_doc_header(note: &[u8]) -> R<NoteHeader> {
    let mut cur = Cur::new(note, 0, note.len());
    let _flex_offset = cur.u32()?;
    let _property_flags = cur.bitfield()?;
    let _field_flags = cur.bitfield()?;
    let format_version = cur.u32()?;
    let _id = cur.short_utf16()?;
    let _file_revision = cur.u32()?;
    let _created_time_us = cur.i64()?;
    let _modified_time_us = cur.i64()?;
    let _width = cur.u32()?;
    let _height = cur.u32()?;
    let _page_h_padding = cur.u32()?;
    let _page_v_padding = cur.u32()?;
    let _min_format_version = cur.u32()?;

    let title_size = cur.u32()? as usize;
    cur.bytes(title_size)?;

    let body_size = cur.u32()? as usize;
    let body_off = cur.pos;
    Ok(NoteHeader { format_version, body_off, body_size })
}

// --- type-22 table object -------------------------------------------------

/// The self-sized wrapper record heading the table and each cell.
struct TableWrap {
    version: u32,
    uuid: String,
    ts1_us: i64,
    bbox: BoundingBox,
    page_width: u32,
    table_index: u32,
}

fn parse_table_wrap(cur: &mut Cur, table_level: bool) -> R<TableWrap> {
    let start = cur.pos;
    let size = cur.u32()? as usize;
    ensure(cur.u16()? == 0, "wrap pad")?;
    ensure(cur.u32()? == 105, "wrap tag != 105")?;
    cur.bytes(8)?; // head: u8 + u16 + 5 bytes, semantics Unknown
    let version = cur.u32()?; // 5400 on tables, 4000 on cells
    ensure(cur.u16()? == 36, "wrap uuid length != 36")?;
    let uuid = std::str::from_utf8(cur.bytes(36)?)
        .map_err(|_| "wrap uuid not ascii")?
        .to_string();
    let ts1_us = cur.i64()?;
    let bbox = rect(cur)?;
    ensure(cur.bytes(5)? == [0u8; 5], "wrap zeros5")?;
    if table_level {
        cur.i64()?; // ts2_us
    }
    let page_width = cur.u32()?;
    ensure(cur.u32()? == 0, "wrap trailing zero")?;
    let mut table_index = 0;
    if table_level {
        ensure(cur.u8()? == 3, "wrap b3 != 3")?;
        table_index = cur.u32()?;
    }
    ensure(cur.pos == start + size, "wrap size mismatch")?;
    Ok(TableWrap { version, uuid, ts1_us, bbox, page_width, table_index })
}

/// Self-sized record: the 4 edge midpoints of a rect (text coords). Cell-level
/// instances carry two extra sub-records of Unknown semantics.
fn parse_table_midpoints(cur: &mut Cur, cell_level: bool) -> R<()> {
    let start = cur.pos;
    let size = cur.u32()? as usize;
    ensure(cur.u16()? == 6, "midpoints tag != 6")?;
    let base = cur.u32()?;
    ensure(base == if cell_level { 91 } else { 0 }, "midpoints base")?;
    ensure(cur.u16()? == 1, "midpoints one")?;
    let _flags = cur.u16()?;
    let npts = cur.u32()?;
    ensure(npts == 4, "midpoints count != 4")?;
    for _ in 0..4 {
        cur.f64()?;
        cur.f64()?;
    }
    ensure(cur.u32()? == 4, "midpoints four")?;
    ensure(cur.bytes(5)? == [0u8; 5], "midpoints zeros5")?;
    if cell_level {
        ensure(cur.u32()? == 19, "cell rec19 size")?;
        ensure(cur.bytes(5)? == T5, "cell rec19 T5")?;
        cur.bytes(14)?; // holds a u32 255 (Unknown)
        let mut tail16 = [0u8; 16];
        tail16[..4].copy_from_slice(&[0x0c, 0, 0, 0]);
        ensure(cur.bytes(16)? == tail16, "cell midpoints tail16")?;
    }
    ensure(cur.pos == start + size, "midpoints size mismatch")?;
    Ok(())
}

/// Chain-sized path record: u32 n_ops, then opcodes (1 moveto / 2 lineto / 6
/// close). Returns the path points (moveto/lineto only).
fn parse_table_path(cur: &mut Cur) -> R<Vec<(f64, f64)>> {
    let size = cur.u32()? as usize;
    let end = cur.pos + size;
    let n_ops = cur.u32()?;
    ensure(n_ops <= 4096, "path op count implausible")?;
    let mut pts = Vec::new();
    for i in 0..n_ops {
        let op = cur.u8()?;
        if op == 6 {
            continue;
        }
        ensure(op == 1 || op == 2, "path opcode")?;
        ensure((op == 1) == (i == 0), "path moveto position")?;
        pts.push((cur.f64()?, cur.f64()?));
    }
    ensure(cur.pos == end, "path size mismatch")?;
    Ok(pts)
}

/// Self-sized outline record: flags, a rect, and the outline path. At cell level
/// the record additionally embeds the cell's Common frame after the path.
fn parse_table_outline(
    cur: &mut Cur,
    cell_level: bool,
    format_version: u32,
) -> R<Option<CommonFrame>> {
    let start = cur.pos;
    let size = cur.u32()? as usize;
    ensure(cur.u16()? == 7, "outline tag != 7")?;
    let base = cur.u32()?;
    ensure(base == if cell_level { 135 } else { 0 }, "outline base")?;
    cur.bytes(7)?; // flags
    ensure(cur.u32()? == 4, "outline four")?;
    cur.bytes(2)?; // pad_a
    rect(cur)?; // (0,0,0,0) on the corpus
    cur.bytes(2)?; // pad_b
    parse_table_path(cur)?;
    ensure(cur.u8()? == 0, "outline pad")?;
    let mut frame = None;
    if cell_level {
        let f = parse_common_frame(cur.data, cur.pos, format_version)?;
        cur.pos += 4 + f.frame_size;
        ensure(cur.bytes(2)? == [0x00, 0x02], "outline frame trailer")?;
        frame = Some(f);
    }
    ensure(cur.pos == start + size, "outline size mismatch")?;
    Ok(frame)
}

/// Chain-sized block of 4 border entries: ARGB + (width, radius_x, radius_y).
fn parse_table_borders(cur: &mut Cur) -> R<[TableBorder; 4]> {
    let size = cur.u32()? as usize;
    let end = cur.pos + size;
    ensure(cur.u32()? == 0, "borders zero")?;
    ensure(cur.bytes(5)? == T5, "borders T5")?;
    let mut items: [TableBorder; 4] = Default::default();
    for item in items.iter_mut() {
        *item = TableBorder {
            argb: cur.u32()?,
            width: cur.f32()?,
            radius_x: cur.f32()?,
            radius_y: cur.f32()?,
        };
    }
    ensure(cur.pos == end, "borders size mismatch")?;
    Ok(items)
}

/// Whole-cell character spans (start == 0, end == char_count) projected to the
/// public `TableCellSpan` shape.
fn cell_spans(frame: &CommonFrame) -> Vec<TableCellSpan> {
    frame
        .spans
        .iter()
        .map(|s| TableCellSpan {
            span_type: s.span_type,
            start: s.start,
            end: s.end,
            interval_type: s.interval_type,
            value: s.value,
        })
        .collect()
}

/// Parse one type-22 table inline object body at `blob[off..off + size]`
/// (pysdocx `parse_table_object`). Byte-exact: any deviation returns `Err`.
fn parse_table_object(blob: &[u8], off: usize, size: usize, format_version: u32) -> R<NoteTable> {
    let mut cur = Cur::new(blob, off, off + size);
    let wrap = parse_table_wrap(&mut cur, true)?;
    parse_table_midpoints(&mut cur, false)?;
    parse_table_outline(&mut cur, false, format_version)?;

    let content_start = cur.pos;
    let content_size = cur.u32()? as usize;
    ensure(content_start + content_size == off + size, "content size mismatch")?;
    ensure(cur.u16()? == TABLE_OBJECT_TYPE as u16, "content tag != 22")?;
    ensure(cur.u16()? == 15, "content u16 != 15")?;
    ensure(cur.u16()? == 0, "content pad")?;
    cur.bytes(3)?; // content_head 01 04 02 (Unknown)
    let _content_u16 = cur.u16()?;
    let n_cols = cur.u32()? as usize;
    ensure((1..=64).contains(&n_cols), "column count implausible")?;
    let mut col_widths = Vec::with_capacity(n_cols);
    for _ in 0..n_cols {
        col_widths.push(cur.f32()?);
    }
    let n_rows = cur.u32()? as usize;
    ensure((1..=4096).contains(&n_rows), "row count implausible")?;

    let mut row_heights = Vec::with_capacity(n_rows);
    let mut cells: Vec<NoteTableCell> = Vec::with_capacity(n_rows * n_cols);
    for r in 0..n_rows {
        let row_size = cur.u32()? as usize;
        let row_end = cur.pos + row_size;
        ensure(cur.bytes(9)? == PRE9, "row preamble")?;
        row_heights.push(cur.f32()?);
        ensure(cur.u32()? as usize == r, "row index")?;
        ensure(cur.u32()? as usize == n_cols, "row column count")?;
        for k in 0..n_cols {
            let cell_size = cur.u32()? as usize;
            let cell_end = cur.pos + cell_size;
            ensure(cur.u32()? == 0, "cell preamble zeros")?;
            ensure(cur.u8()? == 1, "cell preamble m0")?;
            let cell_styled = cur.u8()?;
            ensure(cell_styled <= 1, "cell preamble styled flag")?;
            ensure(cur.bytes(3)? == [0x02, 0x00, 0x00], "cell preamble m2")?;
            ensure(cur.u32()? as usize == k, "cell column index")?;
            ensure(cur.u32()? == 1, "cell one_a")?;
            ensure(cur.u32()? == 1, "cell one_b")?;
            let cell_fill_argb = cur.u32()?;
            let bbox = rect(&mut cur)?;
            ensure(cur.u8()? == 1, "cell b1")?;
            let inner_size = cur.u32()? as usize;
            ensure(cur.pos + inner_size == cell_end, "cell inner size")?;
            let cwrap = parse_table_wrap(&mut cur, false)?;
            ensure(cwrap.ts1_us == 0, "cell wrap timestamp")?;
            ensure(cwrap.bbox == bbox, "cell wrap bbox mismatch")?;
            parse_table_midpoints(&mut cur, true)?;
            let frame = parse_table_outline(&mut cur, true, format_version)?
                .ok_or("cell outline missing frame")?;
            ensure(cur.bytes(15)? == TOKEN15, "cell terminator")?;
            ensure(cur.pos == cell_end, "cell size mismatch")?;
            cells.push(NoteTableCell {
                row: r,
                col: k,
                bbox,
                uuid: cwrap.uuid,
                version: cwrap.version,
                styled: cell_styled == 1,
                fill_argb: cell_fill_argb,
                text: frame.text.clone(),
                spans: cell_spans(&frame),
            });
        }
        ensure(cur.pos == row_end, "row size mismatch")?;
    }

    let tail_bbox = rect(&mut cur)?;
    ensure(tail_bbox == wrap.bbox, "tail bbox != table bbox")?;
    let outer_borders = parse_table_borders(&mut cur)?;
    ensure(cur.u32()? as usize == n_cols, "col width min count")?;
    let mut col_width_min = Vec::with_capacity(n_cols);
    for _ in 0..n_cols {
        col_width_min.push(cur.f32()?);
    }
    ensure(cur.u32()? as usize == n_cols, "col width max count")?;
    let mut col_width_max = Vec::with_capacity(n_cols);
    for _ in 0..n_cols {
        col_width_max.push(cur.f32()?);
    }
    let table_width_max = cur.f32()?;
    let grid_borders = parse_table_borders(&mut cur)?;
    let theme_fill_argb = cur.u32()?;
    ensure_eof(&cur, "table object")?;

    Ok(NoteTable {
        uuid: wrap.uuid,
        bbox: wrap.bbox,
        page_width: wrap.page_width,
        table_index: wrap.table_index,
        n_rows,
        n_cols,
        col_widths,
        row_heights,
        outer_borders,
        grid_borders,
        col_width_min,
        col_width_max,
        table_width_max,
        theme_fill_argb,
        cells,
    })
}

/// Decode every type-22 table object in `note.note`'s body frame (pysdocx
/// `note_doc_tables`). Returns an empty vec if the note has no parseable table.
pub fn note_tables(note: &[u8]) -> Vec<NoteTable> {
    let Ok(header) = parse_note_doc_header(note) else {
        return Vec::new();
    };
    let body_end = header.body_off + header.body_size;
    if body_end > note.len() {
        return Vec::new();
    }
    let body = &note[header.body_off..body_end];
    let frames = find_common_frames(body, header.format_version);
    // The body frame is the largest cleanly-parsing frame; every other frame is
    // a table cell nested in its inline table object.
    let Some((_, body_frame)) = frames.iter().max_by_key(|(_, f)| f.frame_size) else {
        return Vec::new();
    };
    let mut tables = Vec::new();
    for obj in &body_frame.inline_objects {
        if obj.object_type != TABLE_OBJECT_TYPE {
            continue;
        }
        if let Ok(table) = parse_table_object(body, obj.body_off, obj.obj_size, header.format_version)
        {
            tables.push(table);
        }
    }
    tables
}

#[cfg(test)]
mod wrapper_parity {
    //! Byte-exact `parse_text_wrapper` parity gate vs pysdocx.
    //!
    //! For every note.note title/body Text blob and raw type-2 page text box in
    //! the corpus (fixture `tests/fixtures/text_wrapper_pysdocx.json`, regenerate
    //! with the sibling `gen_text_wrapper.py`), this slices the same
    //! `(member, off, size)` window and asserts the Rust wrapper decode matches
    //! pysdocx field-for-field: the four inclusive frame sizes, Shape geometry
    //! (type / original rect / angle / path / control points), ObjectBase
    //! angle+pivot, Text border fields, trailing hash length, and the reached
    //! Common frame's char/span counts. Skips absent samples like the other gates.

    use super::*;
    use std::collections::HashMap;
    use std::io::Read;
    use std::path::{Path, PathBuf};

    fn samples_dir() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../samples")
    }

    fn close(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() <= tol
    }

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }

    fn opt_u64(v: &serde_json::Value) -> Option<u64> {
        v.as_u64()
    }

    fn assert_wrapper(ctx: &str, w: &TextWrapper, e: &serde_json::Value) {
        let u = |k: &str| e[k].as_u64().unwrap();
        assert_eq!(w.base.size as u64, u("object_base_size"), "{ctx}: object_base_size");
        assert_eq!(w.shape_base.size as u64, u("shape_base_size"), "{ctx}: shape_base_size");
        assert_eq!(w.shape.size as u64, u("shape_size"), "{ctx}: shape_size");
        assert_eq!(w.text.size as u64, u("text_size"), "{ctx}: text_size");
        assert_eq!(w.shape_type as u64, u("shape_type"), "{ctx}: shape_type");

        let want_rect = e["original_rect"].as_array().unwrap();
        for (i, g) in w.original_rect.iter().enumerate() {
            assert!(close(*g, want_rect[i].as_f64().unwrap(), 1e-6), "{ctx}: original_rect[{i}]");
        }
        assert!(
            close(w.original_angle as f64, e["original_angle"].as_f64().unwrap(), 1e-3),
            "{ctx}: original_angle"
        );

        match &e["base_angle"] {
            serde_json::Value::Null => assert!(w.base_angle.is_none(), "{ctx}: base_angle != None"),
            v => assert!(
                close(w.base_angle.unwrap() as f64, v.as_f64().unwrap(), 1e-3),
                "{ctx}: base_angle"
            ),
        }
        match &e["base_pivot"] {
            serde_json::Value::Null => assert!(w.base_pivot.is_none(), "{ctx}: base_pivot != None"),
            v => {
                let (gx, gy) = w.base_pivot.unwrap();
                let a = v.as_array().unwrap();
                assert!(
                    close(gx, a[0].as_f64().unwrap(), 1e-6) && close(gy, a[1].as_f64().unwrap(), 1e-6),
                    "{ctx}: base_pivot"
                );
            }
        }

        assert_eq!(hex(&w.path_raw), e["path_hex"].as_str().unwrap(), "{ctx}: path_hex");
        let want_cp = e["control_points"].as_array().unwrap();
        assert_eq!(w.control_points.len(), want_cp.len(), "{ctx}: control_points len");
        for (i, (gx, gy)) in w.control_points.iter().enumerate() {
            let a = want_cp[i].as_array().unwrap();
            assert!(
                close(*gx, a[0].as_f64().unwrap(), 1e-6) && close(*gy, a[1].as_f64().unwrap(), 1e-6),
                "{ctx}: control_points[{i}]"
            );
        }

        assert_eq!(
            w.shape_field_11_f32.map(f64::from),
            e.get("shape_field_11_f32").and_then(serde_json::Value::as_f64),
            "{ctx}: shape_field_11_f32"
        );
        assert_eq!(
            w.ellipsis_type.map(|x| x as u64),
            opt_u64(&e["ellipsis_type"]),
            "{ctx}: ellipsis_type"
        );
        assert_eq!(
            w.text_auto_fit_type.map(|x| x as u64),
            opt_u64(&e["text_auto_fit_type"]),
            "{ctx}: text_auto_fit_type"
        );

        match &e["border_colour"] {
            serde_json::Value::Null => assert!(w.border_colour.is_none(), "{ctx}: border_colour"),
            v => assert_eq!(
                w.border_colour.map(|b| hex(&b)).as_deref(),
                Some(v.as_str().unwrap()),
                "{ctx}: border_colour"
            ),
        }
        match &e["border_width"] {
            serde_json::Value::Null => assert!(w.border_width.is_none(), "{ctx}: border_width"),
            v => assert!(
                close(w.border_width.unwrap() as f64, v.as_f64().unwrap(), 1e-3),
                "{ctx}: border_width"
            ),
        }
        assert_eq!(w.border_type.map(|x| x as u64), opt_u64(&e["border_type"]), "{ctx}: border_type");
        assert_eq!(w.trailing_len as u64, u("trailing_len"), "{ctx}: trailing_len");

        assert_eq!(w.common.is_some(), e["has_common"].as_bool().unwrap(), "{ctx}: has_common");
        if let Some(c) = &w.common {
            assert_eq!(
                c.text.chars().count() as u64,
                u("common_char_count"),
                "{ctx}: common_char_count"
            );
            assert_eq!(c.spans.len() as u64, u("common_span_count"), "{ctx}: common_span_count");
            assert_paragraphs(ctx, c, &e["paragraphs"]);
        }
    }

    /// `structural_paragraphs` (the semantic decode of a Common frame's raw
    /// `paragraphs` records) must match pysdocx `common_frame_paragraphs`
    /// field-for-field: alignment, indent, style, line_spacing, space_before/
    /// after, and list marker.
    fn assert_paragraphs(ctx: &str, frame: &CommonFrame, want: &serde_json::Value) {
        let want = want.as_array().unwrap();
        let got = structural_paragraphs(frame);
        assert_eq!(got.len(), want.len(), "{ctx}: paragraph count");
        for (i, (g, w)) in got.iter().zip(want).enumerate() {
            let pctx = format!("{ctx} paragraph[{i}]");
            let got_align = match g.alignment {
                Alignment::Left => "left",
                Alignment::Right => "right",
                Alignment::Center => "center",
            };
            assert_eq!(got_align, w["alignment"].as_str().unwrap(), "{pctx}: alignment");
            assert_eq!(g.indent as u64, w["indent"].as_u64().unwrap(), "{pctx}: indent");

            let got_style = g.style.map(|s| match s {
                ParagraphStyle::Heading1 => "heading1",
                ParagraphStyle::Heading2 => "heading2",
                ParagraphStyle::Heading3 => "heading3",
                ParagraphStyle::Body1 => "body1",
            });
            assert_eq!(got_style, w["style"].as_str(), "{pctx}: style");

            match w["line_spacing"].as_f64() {
                Some(v) => assert!(
                    close(g.line_spacing.unwrap() as f64, v, 1e-4),
                    "{pctx}: line_spacing"
                ),
                None => assert!(g.line_spacing.is_none(), "{pctx}: line_spacing != None"),
            }
            assert!(
                close(g.space_before as f64, w["space_before"].as_f64().unwrap(), 1e-4),
                "{pctx}: space_before"
            );
            assert!(
                close(g.space_after as f64, w["space_after"].as_f64().unwrap(), 1e-4),
                "{pctx}: space_after"
            );

            match (&g.list, &w["list"]) {
                (None, serde_json::Value::Null) => {}
                (Some(ListItem::Numbered { number }), v) => {
                    assert_eq!(v["type"].as_str().unwrap(), "numbered", "{pctx}: list type");
                    assert_eq!(*number as u64, v["number"].as_u64().unwrap(), "{pctx}: list number");
                }
                (Some(ListItem::Bullet), v) => {
                    assert_eq!(v["type"].as_str().unwrap(), "bullet", "{pctx}: list type");
                }
                (Some(ListItem::Todo { checked }), v) => {
                    assert_eq!(v["type"].as_str().unwrap(), "todo", "{pctx}: list type");
                    assert_eq!(*checked, v["checked"].as_bool().unwrap(), "{pctx}: list checked");
                }
                (g, w) => panic!("{pctx}: list mismatch got={g:?} want={w:?}"),
            }
        }
    }

    #[test]
    fn text_wrappers_match_pysdocx() {
        let fixture_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/text_wrapper_pysdocx.json");
        let fixture: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(fixture_path).unwrap()).unwrap();

        let mut compared = 0usize;
        for (sample_name, entries) in fixture.as_object().unwrap() {
            let sample_path = samples_dir().join(sample_name);
            if !sample_path.exists() {
                eprintln!("skipping: {sample_name} not present");
                continue;
            }
            let file = std::fs::File::open(&sample_path).unwrap();
            let mut archive = zip::ZipArchive::new(file).unwrap();
            let mut members: HashMap<String, Vec<u8>> = HashMap::new();

            for entry in entries.as_array().unwrap() {
                let src = entry["src"].as_str().unwrap();
                if !members.contains_key(src) {
                    let mut buf = Vec::new();
                    archive.by_name(src).unwrap().read_to_end(&mut buf).unwrap();
                    members.insert(src.to_string(), buf);
                }
                let bytes = &members[src];
                let off = entry["off"].as_u64().unwrap() as usize;
                let size = entry["size"].as_u64().unwrap() as usize;
                let blob = &bytes[off..off + size];
                let ctx = format!("{sample_name} {src}@{off}");
                let w = parse_text_wrapper(blob, 0)
                    .unwrap_or_else(|err| panic!("{ctx}: parse failed: {err}"));
                assert_wrapper(&ctx, &w, entry);
                compared += 1;
            }
        }
        assert!(compared > 0, "no fixture samples present");
        eprintln!("compared {compared} text wrappers");
    }
}
