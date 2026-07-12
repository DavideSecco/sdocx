//! Byte-exact `note.note` structural decode: the `text_core::Common` rich-text
//! frame and the type-22 table inline object.
//!
//! Straight port of pysdocx's `pysdocx/note_doc.py` (`parse_common_frame`,
//! `find_common_frames`, the note-doc header, and `parse_table_object` with its
//! `_parse_table_*` helpers) — keep the two in lockstep when either side changes.
//! Unlike the legacy marker-scan table reader (`container::parse_tables`), this
//! parses the whole table object sequentially and byte-exactly: sized
//! wrapper/midpoint/outline records, column widths, length-chained rows and
//! cells with page-coordinate bboxes, per-cell fill + nested Common frame, and
//! the style tail (outer/grid border blocks, per-column width constraints, theme
//! fill). Validated against pysdocx `note_doc_tables` by `tests/note_tables.rs`.

use crate::types::{
    BoundingBox, NoteTable, NoteTableCell, TableBorder, TableCellSpan,
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

/// A parsed `text_core::Common` exclusive frame.
struct CommonFrame {
    frame_size: usize,
    text: String,
    spans: Vec<FrameSpan>,
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
    for _ in 0..paragraph_count {
        let size = win.u16()? as usize;
        ensure(size >= PARAGRAPH_BASE_SIZE, "paragraph record too small")?;
        win.bytes(size)?; // paragraph_type + start + end + extra
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

    Ok(CommonFrame { frame_size, text, spans, inline_objects })
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
