//! Minimal metadata parser for Samsung's proprietary `.spi` raster stream.
//!
//! The pixel payload is a Samsung S Pen screen-codec / Maetel stream, not a
//! standard image format. This module intentionally parses only the stable
//! length-framed wrapper and the dimensions carried by the first chunk.

//! The port below mirrors the Python probe/decoder in `apk-re/scripts/` for the
//! stable, verified pieces of the format. The two known gaps from the handoff
//! remain explicit TODOs: mode 2 reconstruction and mode 3 intra reconstruction.

/// Parsed `.spi` stream metadata.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiInfo {
    pub width: u16,
    pub height: u16,
    pub header_len: u32,
    pub payload_len: u32,
}

impl SpiInfo {
    pub fn tile_cols(self) -> u16 {
        self.width.div_ceil(16)
    }

    pub fn tile_rows(self) -> u16 {
        self.height.div_ceil(16)
    }

    pub fn rgba_len(self) -> Option<usize> {
        usize::from(self.width)
            .checked_mul(usize::from(self.height))?
            .checked_mul(4)
    }
}

/// Parsed `AA 01` image header fields observed in Samsung's Maetel stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiHeader {
    pub field_00: u8,
    pub field_01: u16,
    pub field_02: u16,
    pub width: u16,
    pub height: u16,
    pub color_index: u8,
    pub tile_rows_hint: u16,
    pub field_07: u8,
    pub field_08: bool,
    pub field_09: bool,
    pub field_10: bool,
    pub field_11: bool,
    pub final_reserved_zero: bool,
}

/// Parsed first `AA 02` tile/data-stream header (`FUN_001ccca4` in the native
/// decoder stores these fields in a non-linear in-memory order).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiDataHeader {
    pub field_01: u8,
    pub field_06: u16,
    pub field_00: u8,
    pub field_08: bool,
    pub field_02: u8,
    pub field_03: u8,
    pub field_04: u8,
    pub field_05: u8,
}

/// Fully split `.spi` container: wrapper chunks plus parsed Maetel headers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiStream<'a> {
    pub info: SpiInfo,
    pub header: SpiHeader,
    pub data_header: SpiDataHeader,
    pub payload: &'a [u8],
}

/// MSB-first bit reader used by the Maetel stream.
#[derive(Debug, Clone, Copy)]
pub struct BitReader<'a> {
    data: &'a [u8],
    bit_pos: usize,
}

impl<'a> BitReader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Self { data, bit_pos: 0 }
    }

    pub fn with_bit_pos(data: &'a [u8], bit_pos: usize) -> Self {
        Self { data, bit_pos }
    }

    pub fn bit_pos(&self) -> usize {
        self.bit_pos
    }

    pub fn byte_pos_floor(&self) -> usize {
        self.bit_pos / 8
    }

    pub fn byte_pos_ceil(&self) -> usize {
        self.bit_pos.div_ceil(8)
    }

    pub fn read_bool(&mut self) -> Option<bool> {
        Some(self.read(1)? != 0)
    }

    pub fn read(&mut self, bits: u8) -> Option<u32> {
        if bits > 32 || self.bit_pos.checked_add(bits as usize)? > self.data.len() * 8 {
            return None;
        }
        let mut out = 0u32;
        for _ in 0..bits {
            let byte = *self.data.get(self.bit_pos / 8)?;
            let shift = 7 - (self.bit_pos % 8);
            out = (out << 1) | u32::from((byte >> shift) & 1);
            self.bit_pos += 1;
        }
        Some(out)
    }

    pub fn align_to_next_byte(&mut self) -> usize {
        let before = self.bit_pos;
        self.bit_pos = self.byte_pos_ceil() * 8;
        self.bit_pos - before
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiModeMapCell(pub u8);

impl Default for SpiModeMapCell {
    fn default() -> Self {
        Self(2)
    }
}

#[derive(Debug, Clone)]
pub struct ModeMap {
    width: usize,
    cells: Vec<SpiModeMapCell>,
}

impl ModeMap {
    pub const ENTRIES_PER_TILE: usize = 4;

    pub fn new(tile_cols: usize, tile_rows: usize) -> Self {
        Self {
            width: tile_cols * Self::ENTRIES_PER_TILE,
            cells: vec![
                SpiModeMapCell::default();
                tile_cols * tile_rows * Self::ENTRIES_PER_TILE * Self::ENTRIES_PER_TILE
            ],
        }
    }

    pub fn quadrant(&self, tile_x: usize, tile_y: usize, sub: usize) -> (usize, usize) {
        let col = tile_x * Self::ENTRIES_PER_TILE + (sub & 1) * 2;
        let row = tile_y * Self::ENTRIES_PER_TILE + if sub >= 2 { 2 } else { 0 };
        (col, row)
    }

    pub fn context(
        &self,
        col: usize,
        row: usize,
        tile_y: usize,
        chunk_first_row: bool,
    ) -> (u8, u8) {
        let left = if col > 0 {
            self.cells[row * self.width + col - 1].0
        } else {
            2
        };
        let top_row = tile_y * Self::ENTRIES_PER_TILE;
        let above = if row == 0 || (chunk_first_row && row == top_row) {
            2
        } else {
            self.cells[(row - 1) * self.width + col].0
        };
        (left, above)
    }

    pub fn set(&mut self, col: usize, row: usize, mode: u8, split: bool) {
        if split {
            self.cells[row * self.width + col] = SpiModeMapCell(mode);
            return;
        }
        for dr in 0..2 {
            for dc in 0..2 {
                self.cells[(row + dr) * self.width + col + dc] = SpiModeMapCell(mode);
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct PaletteState {
    pub entries: usize,
    pub index_width: usize,
    pub palette: [u8; 0x300],
    pub indices: Option<Vec<u8>>,
}

const SIZE_CLASS: [u8; 32] = [
    0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
];
const MODE_TO_CONTEXT: [u8; 32] = [
    1, 2, 0, 0, 1, 1, 0, 2, 2, 0, 0, 1, 1, 0, 0, 2, 2, 70, 80, 48, 52, 26, 93, 8, 0, 22, 8, 84, 0,
    14, 0, 8,
];
const RUNLEVEL: [(u8, u8); 128] = [
    (1, 0),
    (1, 1),
    (2, 0),
    (1, 2),
    (3, 0),
    (1, 3),
    (4, 0),
    (1, 4),
    (2, 1),
    (1, 5),
    (5, 0),
    (1, 6),
    (6, 0),
    (1, 7),
    (3, 1),
    (2, 2),
    (1, 8),
    (7, 0),
    (1, 9),
    (8, 0),
    (1, 10),
    (9, 0),
    (4, 1),
    (1, 11),
    (2, 3),
    (1, 12),
    (10, 0),
    (1, 13),
    (3, 2),
    (11, 0),
    (1, 14),
    (5, 1),
    (2, 4),
    (12, 0),
    (1, 15),
    (6, 1),
    (13, 0),
    (2, 5),
    (1, 16),
    (14, 0),
    (1, 17),
    (4, 2),
    (3, 3),
    (7, 1),
    (15, 0),
    (1, 18),
    (2, 6),
    (1, 20),
    (1, 19),
    (16, 0),
    (1, 21),
    (8, 1),
    (17, 0),
    (1, 24),
    (2, 7),
    (1, 22),
    (5, 2),
    (1, 25),
    (3, 4),
    (18, 0),
    (9, 1),
    (1, 23),
    (2, 8),
    (19, 0),
    (4, 3),
    (10, 1),
    (1, 26),
    (20, 0),
    (6, 2),
    (2, 9),
    (21, 0),
    (3, 5),
    (11, 1),
    (1, 27),
    (22, 0),
    (2, 10),
    (7, 2),
    (1, 31),
    (12, 1),
    (1, 30),
    (23, 0),
    (1, 28),
    (1, 29),
    (5, 3),
    (4, 4),
    (1, 32),
    (2, 11),
    (24, 0),
    (13, 1),
    (8, 2),
    (3, 6),
    (25, 0),
    (2, 13),
    (2, 12),
    (14, 1),
    (26, 0),
    (1, 34),
    (1, 33),
    (6, 3),
    (15, 1),
    (27, 0),
    (4, 5),
    (1, 35),
    (2, 14),
    (9, 2),
    (5, 4),
    (28, 0),
    (3, 7),
    (16, 1),
    (29, 0),
    (10, 2),
    (17, 1),
    (30, 0),
    (7, 3),
    (3, 8),
    (31, 0),
    (18, 1),
    (1, 36),
    (11, 2),
    (32, 0),
    (1, 37),
    (3, 9),
    (33, 0),
    (2, 15),
    (19, 1),
    (6, 4),
    (34, 0),
    (1, 0),
];
const SUBBLOCK_MASK_LONG: [u8; 256] = [
    63, 60, 62, 61, 28, 52, 44, 56, 31, 47, 55, 59, 12, 48, 30, 54, 46, 58, 20, 29, 53, 45, 40, 57,
    51, 15, 0, 16, 4, 14, 50, 32, 8, 13, 49, 36, 24, 22, 43, 23, 42, 21, 41, 38, 34, 26, 18, 6, 39,
    10, 2, 33, 17, 27, 5, 37, 35, 1, 25, 9, 19, 7, 11, 3, 60, 63, 62, 61, 28, 52, 44, 56, 12, 48,
    20, 40, 31, 47, 59, 16, 55, 4, 32, 8, 30, 54, 46, 58, 29, 0, 36, 53, 45, 24, 57, 15, 51, 50,
    14, 13, 49, 22, 43, 42, 23, 21, 41, 34, 18, 38, 10, 6, 26, 17, 33, 39, 9, 5, 35, 37, 27, 25,
    19, 11, 2, 7, 1, 3, 60, 63, 61, 62, 28, 12, 52, 44, 56, 48, 20, 40, 4, 16, 8, 32, 0, 31, 59,
    47, 55, 36, 24, 29, 45, 53, 57, 30, 15, 58, 46, 54, 13, 51, 49, 50, 14, 43, 21, 41, 23, 42, 22,
    33, 34, 17, 9, 5, 35, 18, 10, 6, 11, 39, 37, 27, 25, 38, 19, 26, 7, 1, 2, 3, 60, 28, 12, 52,
    44, 56, 63, 20, 48, 40, 4, 16, 8, 61, 32, 62, 0, 36, 24, 31, 59, 29, 47, 55, 57, 53, 45, 13,
    30, 15, 58, 49, 51, 46, 54, 21, 14, 50, 43, 41, 23, 42, 22, 33, 9, 17, 35, 5, 34, 11, 10, 37,
    25, 18, 27, 39, 6, 19, 1, 38, 7, 26, 2, 3,
];
const SUBBLOCK_MASK_SHORT: [u8; 64] = [
    4, 0, 6, 7, 5, 2, 1, 3, 63, 61, 60, 62, 53, 59, 55, 57, 29, 45, 47, 31, 52, 28, 56, 44, 54, 58,
    48, 30, 49, 13, 46, 20, 21, 41, 51, 15, 12, 43, 40, 23, 50, 14, 22, 42, 37, 25, 24, 36, 32, 8,
    16, 17, 39, 4, 26, 9, 27, 33, 5, 11, 38, 7, 10, 19,
];
const QUANT_GROUP: [u8; 64] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 0, 64, 0, 64, 0, 64, 0, 64, 0, 64, 0,
    64, 0,
];
const SCAN_1_0: [u16; 4] = [0, 2, 1, 3];
const SCAN_1_1: [u16; 4] = [0, 1, 2, 3];
const SCAN_1_2: [u16; 4] = [0, 2, 1, 3];
const SCAN_2_0: [u16; 16] = [0, 4, 1, 2, 5, 8, 12, 9, 6, 3, 7, 10, 13, 14, 11, 15];
const SCAN_2_1: [u16; 16] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
const SCAN_2_2: [u16; 16] = [0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15];
const SCAN_3_0: [u16; 64] = [
    0, 8, 1, 2, 9, 16, 24, 17, 10, 3, 4, 11, 18, 25, 32, 40, 33, 26, 19, 12, 5, 6, 13, 20, 27, 34,
    41, 48, 56, 49, 42, 35, 28, 21, 14, 7, 15, 22, 29, 36, 43, 50, 57, 58, 51, 44, 37, 30, 23, 31,
    38, 45, 52, 59, 60, 53, 46, 39, 47, 54, 61, 62, 55, 63,
];
const SCAN_3_1: [u16; 64] = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49,
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
];
const SCAN_3_2: [u16; 64] = [
    0, 8, 16, 24, 32, 40, 48, 56, 1, 9, 17, 25, 33, 41, 49, 57, 2, 10, 18, 26, 34, 42, 50, 58, 3,
    11, 19, 27, 35, 43, 51, 59, 4, 12, 20, 28, 36, 44, 52, 60, 5, 13, 21, 29, 37, 45, 53, 61, 6,
    14, 22, 30, 38, 46, 54, 62, 7, 15, 23, 31, 39, 47, 55, 63,
];
impl Default for PaletteState {
    fn default() -> Self {
        Self {
            entries: 0,
            index_width: 0,
            palette: [0; 0x300],
            indices: None,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SpiError {
    #[error("invalid spi stream")]
    InvalidStream,
    #[error("unsupported mode")]
    UnsupportedMode,
}

/// Parse enough of a Samsung `.spi` stream to identify it and read dimensions.
///
/// Observed framing:
/// - `u32le header_len`
/// - header chunk beginning with `AA 01`
/// - `u32le payload_len`
/// - payload chunk beginning with `AA 02`
///
/// The header stores width/height as big-endian u16 values at offsets 15/17 in
/// the whole file (offsets 11/13 inside the `AA 01` header chunk).
pub fn parse_info(data: &[u8]) -> Option<SpiInfo> {
    Some(parse_stream(data)?.info)
}

/// Parse the length-framed `.spi` stream and its two Maetel chunk headers.
pub fn parse_stream(data: &[u8]) -> Option<SpiStream<'_>> {
    if data.len() < 30 {
        return None;
    }

    let header_len = u32::from_le_bytes(data.get(0..4)?.try_into().ok()?);
    let header_len_usize = usize::try_from(header_len).ok()?;
    if header_len_usize < 15 {
        return None;
    }

    let header_start = 4usize;
    let header_end = header_start.checked_add(header_len_usize)?;
    if data.get(header_start..header_start + 2)? != [0xAA, 0x01] {
        return None;
    }
    let header = parse_header_chunk(data.get(header_start..)?)?;
    if header_end.checked_add(6)? > data.len() {
        return None;
    }

    let width = header.width;
    let height = header.height;
    if width == 0 || height == 0 {
        return None;
    }

    let payload_len = u32::from_le_bytes(data.get(header_end..header_end + 4)?.try_into().ok()?);
    let payload_start = header_end + 4;
    if data.get(payload_start..payload_start + 2)? != [0xAA, 0x02] {
        return None;
    }
    let payload_len_usize = usize::try_from(payload_len).ok()?;
    let payload_end = payload_start.checked_add(payload_len_usize)?;
    if payload_end > data.len() {
        return None;
    }
    let payload = data.get(payload_start..payload_end)?;
    let data_header = parse_data_chunk_header(payload)?;

    Some(SpiStream {
        info: SpiInfo {
            width,
            height,
            header_len,
            payload_len,
        },
        header,
        data_header,
        payload,
    })
}

fn parse_header_chunk(chunk: &[u8]) -> Option<SpiHeader> {
    if chunk.len() < 20 || chunk.get(0..2)? != [0xAA, 0x01] {
        return None;
    }
    let tag_size = u32::from_be_bytes(chunk.get(2..6)?.try_into().ok()?);
    if tag_size == 0 || usize::try_from(tag_size).ok()? > chunk.len() {
        return None;
    }
    let mut bits = BitReader::new(chunk.get(6..)?);
    let field_00 = u8::try_from(bits.read(8)?).ok()?;
    let field_01 = u16::try_from(bits.read(16)?).ok()?;
    let field_02 = u16::try_from(bits.read(16)?).ok()?;
    let width = u16::try_from(bits.read(16)?).ok()?;
    let height = u16::try_from(bits.read(16)?).ok()?;
    let color_index = u8::try_from(bits.read(8)?).ok()?;
    let tile_rows_hint = u16::try_from(bits.read(16)?).ok()?;
    let field_07 = u8::try_from(bits.read(8)?).ok()?;
    if field_07 & 0xfe > 5 {
        return None;
    }
    let field_08 = bits.read_bool()?;
    let field_09 = bits.read_bool()?;
    let field_10 = bits.read_bool()?;
    let field_11 = bits.read_bool()?;
    if bits.read(3)? != 0 {
        return None;
    }
    let final_reserved_zero = bits.read_bool()?;
    if final_reserved_zero {
        return None;
    }
    Some(SpiHeader {
        field_00,
        field_01,
        field_02,
        width,
        height,
        color_index,
        tile_rows_hint,
        field_07,
        field_08,
        field_09,
        field_10,
        field_11,
        final_reserved_zero,
    })
}

fn parse_data_chunk_header(chunk: &[u8]) -> Option<SpiDataHeader> {
    if chunk.len() < 10 || chunk.get(0..2)? != [0xAA, 0x02] {
        return None;
    }
    let tag_size = u32::from_be_bytes(chunk.get(2..6)?.try_into().ok()?);
    if tag_size == 0 || usize::try_from(tag_size).ok()? > chunk.len() {
        return None;
    }
    let mut bits = BitReader::new(chunk.get(6..)?);
    let field_01 = u8::try_from(bits.read(8)?).ok()?;
    let field_06 = u16::try_from(bits.read(16)?).ok()?;
    let field_00 = u8::try_from(bits.read(8)?).ok()?;
    let field_08 = bits.read_bool()?;
    let field_02 = u8::try_from(bits.read(2)?).ok()?;
    let field_03 = u8::try_from(bits.read(8)?).ok()?;
    let field_04 = u8::try_from(bits.read(8)?).ok()?;
    let field_05 = u8::try_from(bits.read(8)?).ok()?;
    if bits.read(4)? != 0 {
        return None;
    }
    if bits.read_bool()? {
        return None;
    }
    Some(SpiDataHeader {
        field_01,
        field_06,
        field_00,
        field_08,
        field_02,
        field_03,
        field_04,
        field_05,
    })
}

fn read_unary_prefix(br: &mut BitReader<'_>) -> Option<u32> {
    let mut zeros = 0u32;
    while !br.read_bool()? {
        zeros += 1;
    }
    Some(zeros)
}

fn read_exp_golomb(br: &mut BitReader<'_>) -> Option<u32> {
    let zeros = read_unary_prefix(br)?;
    let payload = if zeros == 0 { 0 } else { br.read(zeros as u8)? };
    Some((1u32 << zeros) + payload - 1)
}

fn read_biased_value(br: &mut BitReader<'_>, zeros: u32) -> Option<u32> {
    let payload = if zeros == 0 { 0 } else { br.read(zeros as u8)? };
    Some(payload + (1u32 << zeros))
}

fn zigzag_decode_native(code: u32) -> i32 {
    let sign = (code & 1) as i32;
    ((-(sign)) ^ ((code >> 1) as i32)) + sign
}

pub fn read_tile_mode(br: &mut BitReader<'_>) -> Option<u8> {
    if br.read_bool()? {
        return Some(0);
    }
    if br.read_bool()? {
        return Some(1);
    }
    Some((br.read(2)? + 2) as u8)
}

pub fn mode0_motion(tile_x: usize) -> (i32, i32) {
    if tile_x == 0 { (0, 16) } else { (16, 0) }
}

pub fn read_mode1_residual(br: &mut BitReader<'_>) -> Option<(i32, i32)> {
    if br.read_bool()? {
        return Some((0, 16));
    }
    let dx = zigzag_decode_native(read_exp_golomb(br)? + 1) * 16;
    let dy = (read_exp_golomb(br)? as i32) * 16;
    Some((dx, dy))
}

/// `color_index` -> pixel-format code, read by `FUN_001c0608` through the GOT
/// slot at Ghidra `0x204ab0` (table at file vaddr `0x3073c`).
///
/// The distinction matters: `color_index` is a small index (0..15) stored in the
/// `AA 01` header, *not* the format code itself. Comparing the index directly
/// against 43/500..503 silently yields one plane for the formula stream
/// (`color_index = 4` -> format 500 -> **two** planes) and desyncs everything.
const FORMAT_TABLE: [i32; 8] = [13, 43, 400, 401, 500, 501, 502, 503];

/// Number of plane passes per chunk: `FUN_001c0124` loops `0..=ctx[0x401]`, and
/// `FUN_001c0608` sets that byte from the format code.
pub fn plane_count_for(color_index: u8) -> u8 {
    let Some(&format) = FORMAT_TABLE.get(usize::from(color_index)) else {
        return 1;
    };
    if format == 43 || (500..=503).contains(&format) {
        2
    } else {
        1
    }
}

/// Whether the format carries three colour components (`FUN_001c0608:174`).
pub fn three_components_for(color_index: u8) -> bool {
    FORMAT_TABLE
        .get(usize::from(color_index))
        .is_some_and(|&format| (200..600).contains(&format))
}

fn read_block_symbol(br: &mut BitReader<'_>) -> Option<u8> {
    const SYMBOL_ESCAPE_PREFIX: u32 = 0x15;
    const SYMBOL_ESCAPE_BASE: u8 = 0x54;
    let zeros = read_unary_prefix(br)?;
    let v = br.read(2)? as u8;
    if zeros < SYMBOL_ESCAPE_PREFIX {
        return Some((zeros as u8).saturating_mul(4) + v);
    }
    if v > 2 {
        return u8::try_from(br.read(8)?).ok();
    }
    Some(SYMBOL_ESCAPE_BASE | v)
}

fn decode_symbol_block(br: &mut BitReader<'_>, count: usize) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(count);
    let mut cur: u8 = 0;
    let mut cmp_prev: u8 = 0xff;
    while out.len() < count {
        let prev = cur;
        if prev == cmp_prev {
            let run = read_exp_golomb(br)? as usize;
            if run > 0 {
                out.extend(std::iter::repeat_n(cmp_prev, run));
            }
        }
        let sym = read_block_symbol(br)?;
        out.push(sym);
        cur = sym;
        cmp_prev = prev;
    }
    Some(out)
}

// Mode 2 pixel reconstruction is NOT ported: the native predictor is still
// unidentified. See `apk-re/SPI-HANDOFF.md` §7.1 -- the `a64_TBL` sequence is
// decoded (byte shuffle, `(s >> 1) ^ -(s & 1)`, net permutation = identity) but
// no linear DPCM reproduces the native blocks. Already tried and ruled out
// against the real fixture, do not repeat: straight vertical accumulation
// (0/27 tiles), all six symbol-block-to-component assignments (0/27), and
// predictor shifts of -1/0/+1/+2 (best leaves 20% of residuals above +-8).
// Parsing still runs, so the bitstream stays in sync; the block is left zeroed.

/// `FUN_001d4000`'s "no mode here yet" sentinel, read through a `0x11 -> 2` map.
const MODE_CONTEXT_EMPTY: u8 = 0x11;
const MODE_CONTEXT_DEFAULT: u8 = 2;

/// Scan order for a (size class, context) pair, from the pointer table at
/// Ghidra `0x204b08`. Lengths follow the size class: 4, 16 or 64 coefficients.
fn scan_order(size_class: usize, context: usize) -> Option<&'static [u16]> {
    Some(match (size_class, context) {
        (1, 0) => &SCAN_1_0,
        (1, 1) => &SCAN_1_1,
        (1, 2) => &SCAN_1_2,
        (2, 0) => &SCAN_2_0,
        (2, 1) => &SCAN_2_1,
        (2, 2) => &SCAN_2_2,
        (3, 0) => &SCAN_3_0,
        (3, 1) => &SCAN_3_1,
        (3, 2) => &SCAN_3_2,
        _ => return None,
    })
}

/// Port of `FUN_001d4000` -- the tree B mode coder (plane 1, mode 3).
///
/// Context-modelled against the two already-decoded neighbours, each read
/// through the `0x11 -> 2` mapping:
///
/// ```text
/// 1         predict from a neighbour; when the two agree that is all
/// 1 b       ...they disagree, so one bit picks: 0 = left, 1 = above
/// 0 1 b     short escape, coding exactly 2 or 0x11
/// 0 0 vvvv  explicit 4-bit value, biased past whatever context predicted
/// ```
fn decode_mode_with_context(br: &mut BitReader<'_>, left: u8, above: u8) -> Option<u8> {
    let left = if left == MODE_CONTEXT_EMPTY {
        MODE_CONTEXT_DEFAULT
    } else {
        left
    };
    let above = if above == MODE_CONTEXT_EMPTY {
        MODE_CONTEXT_DEFAULT
    } else {
        above
    };

    if br.read_bool()? {
        if left == above {
            return Some(left);
        }
        return Some(if br.read_bool()? { above } else { left });
    }
    if br.read_bool()? {
        return Some(if br.read_bool()? {
            MODE_CONTEXT_EMPTY
        } else {
            MODE_CONTEXT_DEFAULT
        });
    }

    let mut value = br.read(4)?;
    // Skip the values the context already predicts, so the explicit code never
    // spends a symbol on something the cheaper branches could have said.
    if value > 1 || u32::from(left) <= value {
        value += 1;
    }
    if value > 1 && left != MODE_CONTEXT_DEFAULT && u32::from(left) <= value {
        value += 1;
    }
    Some((value & 0xff) as u8)
}

/// Escape threshold in the run/level code; below it the value indexes the
/// static `(level, run)` table instead.
const RUNLEVEL_ESCAPE_PREFIX: u32 = 6;
const RUNLEVEL_ESCAPE_BIAS: u32 = 0x80;

/// Port of `FUN_001d2874` -- the tree B coefficient decoder (plane 1, mode 3).
///
/// ```text
/// 1 bit       split; halves the block, from 8x8 to 4x4
/// n modes     FUN_001d4000 per sub-block, n = 1 unsplit, 4 split
/// prefix      selects a sub-block presence mask from a static table
/// per present sub-block:
///     count   how many (run, level) pairs follow, biased by 2**z
///     pairs   prefix z, then z+1 bits whose last bit is the sign
/// ```
///
/// Only the bit consumption matters here: the decoded coefficients feed the
/// intra reconstruction, which is not ported (see `decode_spi`).
/// Decoder state `FUN_001d2874` branches on. Constant across the reference
/// sample (`tile[0x946] = 1`, `tile[0x1c] = 8`, `tile[0x38] = 0`), but carried
/// explicitly rather than hardcoded.
#[derive(Debug, Clone, Copy)]
pub struct CoefficientBlockState {
    pub split_enabled: bool,
    pub dim_code: usize,
    pub quant: usize,
}

impl Default for CoefficientBlockState {
    fn default() -> Self {
        Self {
            split_enabled: true,
            dim_code: 8,
            quant: 0,
        }
    }
}

fn decode_coefficient_block(
    br: &mut BitReader<'_>,
    mode_map: &mut ModeMap,
    tile_x: usize,
    tile_y: usize,
    sub: usize,
    chunk_first_row: bool,
    state: CoefficientBlockState,
) -> Option<()> {
    let CoefficientBlockState {
        split_enabled,
        dim_code,
        quant,
    } = state;
    let tables = coefficient_tables();

    let split = if split_enabled {
        br.read_bool()?
    } else {
        false
    };
    let block_dim = dim_code >> u32::from(split);
    let size_class = usize::from(*tables.size_class.get(block_dim)?);
    let n_modes = if split { 4 } else { 1 };

    let (col0, row0) = mode_map.quadrant(tile_x, tile_y, sub);
    let mut modes = [0u8; 4];
    for (k, slot) in modes.iter_mut().enumerate().take(n_modes) {
        let (col, row) = (col0 + (k & 1), row0 + (k >> 1));
        let (left, above) = mode_map.context(col, row, tile_y, chunk_first_row);
        let mode = decode_mode_with_context(br, left, above)?;
        *slot = mode;
        mode_map.set(col, row, mode, split);
    }

    let zeros = read_unary_prefix(br)?;
    let mask = if block_dim != 4 {
        if zeros > 7 {
            return None;
        }
        *tables.subblock_mask_short.get(zeros as usize)?
    } else {
        if quant > 0x33 {
            return None;
        }
        let group = usize::from(*tables.quant_group.get(quant)?) * 0x40;
        if zeros == 0 {
            *tables.subblock_mask_long.get(group)?
        } else {
            let value = br.read(zeros as u8)? + (1 << zeros) - 1;
            if value > 0x3f {
                return None;
            }
            *tables.subblock_mask_long.get(group + value as usize)?
        }
    };

    for (k, mode) in modes.iter().enumerate().take(n_modes) {
        if (mask >> ((n_modes + 1) - k)) & 1 == 0 {
            continue; // sub-block carries no coefficients
        }
        let context = if block_dim == 0x10 || *mode == MODE_CONTEXT_EMPTY {
            0
        } else {
            usize::from(*tables.mode_to_context.get(usize::from(*mode))?)
        };
        let scan_len = scan_order(size_class, context)?.len();

        let count_zeros = read_unary_prefix(br)?;
        let count = read_biased_value(br, count_zeros)? as usize;
        if count > block_dim * block_dim {
            return None;
        }

        let mut position = 0usize;
        for _ in 0..count {
            let zeros = read_unary_prefix(br)?;
            let mut bits = 0u32;
            for _ in 0..=zeros {
                bits = (bits << 1) | br.read(1)?;
            }
            let value = (1u32 << zeros) + (bits >> 1);
            let run = if zeros > RUNLEVEL_ESCAPE_PREFIX {
                let shift = size_class * 2;
                (value.checked_sub(RUNLEVEL_ESCAPE_BIAS)?) & ((1 << shift) - 1)
            } else {
                if value > 0x7f {
                    return None;
                }
                u32::from(tables.runlevel.get(value as usize - 1)?.1)
            };
            position += run as usize + 1;
            if position > scan_len {
                return None;
            }
        }
    }
    Some(())
}

fn decode_palette_indices(br: &mut BitReader<'_>, index_width: usize) -> Option<Vec<u8>> {
    const PALETTE_PIXELS: usize = 0x100;
    let mut out = Vec::with_capacity(PALETTE_PIXELS);
    while out.len() < PALETTE_PIXELS {
        let index = if index_width == 0 {
            0
        } else {
            u8::try_from(br.read(index_width as u8)?).ok()?
        };
        let run = read_exp_golomb(br)? as usize;
        if run + out.len() > 0xff {
            return None;
        }
        out.extend(std::iter::repeat_n(index, run + 1));
    }
    Some(out)
}

#[derive(Debug, Clone)]
pub struct SpiPaletteDecode {
    pub entries: usize,
    pub index_width: usize,
    pub palette: [u8; 0x300],
    pub indices: Option<Vec<u8>>,
}

const TILE: usize = 16;
const BLOCK_PIXELS: usize = TILE * TILE;
const COMPONENTS: usize = 4;

#[derive(Debug, Clone)]
pub struct Blocks {
    pub data: [Vec<u8>; COMPONENTS],
}

impl Default for Blocks {
    fn default() -> Self {
        Self::new()
    }
}

impl Blocks {
    pub fn new() -> Self {
        Self {
            data: std::array::from_fn(|_| vec![0; BLOCK_PIXELS]),
        }
    }

    pub fn fill(&mut self, component: usize, value: u8) {
        self.data[component].fill(value);
    }

    pub fn as_bytes(&self) -> Vec<u8> {
        self.data.iter().flat_map(|b| b.iter().copied()).collect()
    }
}

#[derive(Debug, Clone)]
pub struct Frame {
    pub width: usize,
    pub height: usize,
    pub planes: [Vec<u8>; COMPONENTS],
}

impl Frame {
    pub fn new(tile_cols: usize, tile_rows: usize) -> Self {
        let width = tile_cols * TILE;
        let height = tile_rows * TILE;
        Self {
            width,
            height,
            planes: std::array::from_fn(|_| vec![0; width * height]),
        }
    }

    pub fn blit_block(&mut self, component: usize, x: usize, y: usize, block: &[u8]) {
        for row in 0..TILE {
            let dst = (y + row) * self.width + x;
            let src = row * TILE;
            self.planes[component][dst..dst + TILE].copy_from_slice(&block[src..src + TILE]);
        }
    }

    pub fn copy_region(&mut self, component: usize, sx: isize, sy: isize, x: usize, y: usize) {
        if sx < 0 || sy < 0 || sx as usize + TILE > self.width || sy as usize + TILE > self.height {
            return;
        }
        let sx = sx as usize;
        let sy = sy as usize;
        // `copy_within` has memmove semantics, so overlapping source and
        // destination are fine -- and it avoids cloning the whole plane once per
        // tile, which this does ~2500 times per image.
        let plane = &mut self.planes[component];
        for row in 0..TILE {
            let src = (sy + row) * self.width + sx;
            let dst = (y + row) * self.width + x;
            plane.copy_within(src..src + TILE, dst);
        }
    }

    pub fn to_rgba(&self, width: usize, height: usize) -> Vec<u8> {
        let mut out = vec![0; width * height * 4];
        for row in 0..height {
            let base = row * self.width;
            for col in 0..width {
                let o = (row * width + col) * 4;
                out[o] = self.planes[0][base + col];
                out[o + 1] = self.planes[1][base + col];
                out[o + 2] = self.planes[2][base + col];
                out[o + 3] = self.planes[3][base + col];
            }
        }
        out
    }
}

#[derive(Debug, Clone, Copy)]
pub struct CoefficientTables {
    pub size_class: &'static [u8; 32],
    pub mode_to_context: &'static [u8; 32],
    pub runlevel: &'static [(u8, u8); 128],
    pub subblock_mask_long: &'static [u8; 256],
    pub subblock_mask_short: &'static [u8; 64],
    pub quant_group: &'static [u8; 64],
}

pub const fn coefficient_tables() -> CoefficientTables {
    CoefficientTables {
        size_class: &SIZE_CLASS,
        mode_to_context: &MODE_TO_CONTEXT,
        runlevel: &RUNLEVEL,
        subblock_mask_long: &SUBBLOCK_MASK_LONG,
        subblock_mask_short: &SUBBLOCK_MASK_SHORT,
        quant_group: &QUANT_GROUP,
    }
}

impl Default for SpiPaletteDecode {
    fn default() -> Self {
        Self {
            entries: 0,
            index_width: 0,
            palette: [0; 0x300],
            indices: None,
        }
    }
}

pub fn consume_mode4_palette(
    br: &mut BitReader<'_>,
    prev_palette_entries: usize,
    prev_index_width: usize,
    state: Option<&mut SpiPaletteDecode>,
) -> Option<(usize, usize)> {
    if !br.read_bool()? {
        if prev_index_width == 0 {
            if let Some(state) = state {
                state.indices = None;
            }
            return Some((prev_palette_entries, prev_index_width));
        }
        let indices = decode_palette_indices(br, prev_index_width)?;
        if let Some(state) = state {
            state.indices = Some(indices);
        }
        return Some((prev_palette_entries, prev_index_width));
    }

    let fresh = br.read_bool()?;
    let index_width = br.read(4)? as usize;
    let already = if fresh { 0 } else { prev_palette_entries * 3 };
    if index_width == 0 {
        let flat = [br.read(8)? as u8, br.read(8)? as u8, br.read(8)? as u8];
        if let Some(state) = state {
            state.palette[0..3].copy_from_slice(&flat);
            state.indices = None;
        }
        return Some((if fresh { 1 } else { prev_palette_entries }, 0));
    }
    let entries = br.read(index_width as u8)? as usize + 1;
    if entries > 0x100 {
        return None;
    }
    // Only the entries not already carried over are transmitted, and they have
    // to be *stored*: reading and dropping them keeps the bit count right but
    // leaves every fresh-palette tile with black pixels.
    let mut state = state;
    for offset in already..already.max(entries * 3) {
        let byte = br.read(8)? as u8;
        if let Some(slot) = state.as_deref_mut().and_then(|s| s.palette.get_mut(offset)) {
            *slot = byte;
        }
    }
    let indices = decode_palette_indices(br, index_width)?;
    if let Some(state) = state {
        state.indices = Some(indices);
    }
    Some((entries, index_width))
}

pub fn consume_mode5_raw(br: &mut BitReader<'_>, plane: usize) -> Option<[Vec<u8>; 3]> {
    let _skipped = br.align_to_next_byte();
    let block_count = if plane == 1 { 1 } else { 3 };
    let mut planes = [Vec::new(), Vec::new(), Vec::new()];
    for slot in planes.iter_mut().take(block_count) {
        let mut buf = Vec::with_capacity(256);
        for _ in 0..256 {
            buf.push(u8::try_from(br.read(8)?).ok()?);
        }
        *slot = buf;
    }
    for slot in planes.iter_mut().skip(block_count) {
        *slot = vec![0x80; 256];
    }
    Some(planes)
}

/// One `AA 02` chunk: where it starts and how many tile rows it owns.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiChunk {
    pub index: usize,
    pub offset: usize,
    pub rows: usize,
}

/// Locate every `AA 02` chunk in the payload.
///
/// A raw `AA 02` byte pair also occurs inside compressed data, so each
/// candidate is validated two ways: the header's reserved bits must be zero
/// (`parse_data_chunk_header`) and `field_06` must equal the chunk index.
pub fn find_tile_chunks(
    payload: &[u8],
    tile_rows: usize,
    tile_rows_hint: usize,
) -> Option<Vec<SpiChunk>> {
    if tile_rows_hint == 0 {
        return None;
    }
    let wanted = tile_rows.div_ceil(tile_rows_hint);
    let mut chunks = Vec::with_capacity(wanted);
    let mut search_from = 0usize;

    for index in 0..wanted {
        loop {
            let offset = payload
                .get(search_from..)?
                .windows(2)
                .position(|w| w == [0xaa, 0x02])
                .map(|p| p + search_from)?;
            match parse_data_chunk_header(payload.get(offset..)?) {
                Some(header) if usize::from(header.field_06) == index => {
                    let rows_done = index * tile_rows_hint;
                    chunks.push(SpiChunk {
                        index,
                        offset,
                        rows: tile_rows_hint.min(tile_rows.saturating_sub(rows_done)),
                    });
                    search_from = offset + 1;
                    break;
                }
                _ => search_from = offset + 1,
            }
        }
    }
    Some(chunks)
}

/// Bytes the `AA 02` chunk header occupies before the first tile.
const CHUNK_HEADER_BITS: usize = 8 + 8 + 32 + 8 + 16 + 8 + 1 + 2 + 8 + 8 + 8 + 4 + 1;

/// What one tile of the walk consumed, for parity checking against the native
/// per-tile trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpiTileTrace {
    pub plane: u8,
    pub tile_index: usize,
    pub mode: u8,
    /// Bit position, relative to the start of the payload, right after the mode
    /// VLC -- i.e. where the payload handler begins.
    pub payload_start_bit: usize,
    pub payload_bits: usize,
}

/// Result of a full decode.
pub struct SpiDecoded {
    pub info: SpiInfo,
    pub frame: Frame,
    pub tiles: Vec<SpiTileTrace>,
    /// The four 16x16 component blocks each tile produced, keyed by
    /// `(plane, tile_index)`. Modes 0 and 1 copy from the frame instead of
    /// filling blocks, so theirs stay zeroed.
    pub blocks: std::collections::BTreeMap<(u8, usize), Vec<u8>>,
}

/// Decode a `.spi` stream to planes.
///
/// Mirrors the verified Python reference in `apk-re/scripts/spi_decode.py`:
/// chunks are located independently, and within each chunk the **plane pass is
/// the outer loop**, with a byte realignment between passes
/// (`FUN_001c0124:84-87`).
///
/// Two reconstruction paths are deliberately absent, and produce zeroed blocks
/// rather than guesses -- their *parsing* is complete, so the bitstream stays in
/// sync and every other tile decodes correctly:
///
/// * mode 2 (27 tiles on the reference sample, ~1.6% of RGB): predictor
///   unidentified, see `apk-re/SPI-HANDOFF.md` §7.1;
/// * mode 3 (327 tiles, all of the alpha plane): a full directional intra coder
///   plus inverse transform, see §7.2.
pub fn decode_spi(data: &[u8]) -> Option<SpiDecoded> {
    let stream = parse_stream(data)?;
    let tile_cols = usize::from(stream.info.tile_cols());
    let tile_rows = usize::from(stream.info.tile_rows());
    let tile_rows_hint = usize::from(stream.header.tile_rows_hint);
    let planes = usize::from(plane_count_for(stream.header.color_index));
    let chunks = find_tile_chunks(stream.payload, tile_rows, tile_rows_hint)?;

    let mut frame = Frame::new(tile_cols, tile_rows);
    let mut mode_map = ModeMap::new(tile_cols, tile_rows);
    let mut palette_state: Vec<SpiPaletteDecode> =
        (0..planes).map(|_| SpiPaletteDecode::default()).collect();
    let mut blocks_out = std::collections::BTreeMap::new();
    let mut tiles = Vec::with_capacity(tile_cols * tile_rows * planes);

    for chunk in &chunks {
        let mut br = BitReader::with_bit_pos(stream.payload, chunk.offset * 8 + CHUNK_HEADER_BITS);

        for plane in 0..planes {
            let components: &[usize] = if plane == 0 { &[0, 1, 2] } else { &[3] };

            for local in 0..tile_cols * chunk.rows {
                let index = chunk.index * tile_rows_hint * tile_cols + local;
                let tile_x = local % tile_cols;
                let tile_y = index / tile_cols;
                let chunk_first_row = local < tile_cols;

                let mode = read_tile_mode(&mut br)?;
                let payload_start_bit = br.bit_pos();
                let mut blocks = Blocks::new();
                let mut motion = None;

                match (mode, plane) {
                    (0, _) => motion = Some(mode0_motion(tile_x)),
                    (1, _) => motion = Some(read_mode1_residual(&mut br)?),
                    (2, 0) => {
                        // FUN_001cdddc reads one bit into tile[0x9bd]; with it
                        // clear -- the only case in the corpus -- three symbol
                        // blocks follow, one per colour component.
                        if br.read_bool()? {
                            return None;
                        }
                        for _ in 0..3 {
                            decode_symbol_block(&mut br, BLOCK_PIXELS)?;
                        }
                        // Reconstruction not ported: blocks stay zeroed.
                    }
                    (3, 1) => {
                        // FUN_001cef0c consumes nothing; FUN_001d0044 reads one
                        // bit and then delegates to four FUN_001d2874 calls.
                        br.read_bool()?;
                        for sub in 0..4 {
                            decode_coefficient_block(
                                &mut br,
                                &mut mode_map,
                                tile_x,
                                tile_y,
                                sub,
                                chunk_first_row,
                                CoefficientBlockState::default(),
                            )?;
                        }
                        // Intra reconstruction not ported: block stays zeroed.
                    }
                    (4, 0) => {
                        let state = palette_state.get_mut(plane)?;
                        let (entries, index_width) = consume_mode4_palette(
                            &mut br,
                            state.entries,
                            state.index_width,
                            Some(state),
                        )?;
                        state.entries = entries;
                        state.index_width = index_width;
                        match &state.indices {
                            Some(indices) => {
                                for (pixel, palette_index) in
                                    indices.iter().enumerate().take(BLOCK_PIXELS)
                                {
                                    let base = usize::from(*palette_index) * 3;
                                    for component in 0..3 {
                                        blocks.data[component][pixel] =
                                            *state.palette.get(base + component)?;
                                    }
                                }
                            }
                            None => {
                                for component in 0..3 {
                                    blocks.fill(component, state.palette[component]);
                                }
                            }
                        }
                    }
                    (5, _) => {
                        let raw = consume_mode5_raw(&mut br, plane)?;
                        for (slot, component) in components.iter().enumerate() {
                            let source = if plane == 0 { slot } else { 0 };
                            blocks.data[*component].copy_from_slice(&raw[source]);
                        }
                    }
                    // PTR_FUN_0020c418[1 * 6 + 2] and [1 * 6 + 4] both point at
                    // FUN_001cef00, whose body is `return 0xffffff36`: modes 2
                    // and 4 cannot occur on plane 1. Seeing one means the bit
                    // position is already wrong.
                    _ => return None,
                }

                let payload_bits = br.bit_pos() - payload_start_bit;
                tiles.push(SpiTileTrace {
                    plane: plane as u8,
                    tile_index: index,
                    mode,
                    payload_start_bit,
                    payload_bits,
                });

                let (px, py) = (tile_x * TILE, tile_y * TILE);
                match motion {
                    Some((dx, dy)) => {
                        for component in components {
                            frame.copy_region(
                                *component,
                                px as isize - dx as isize,
                                py as isize - dy as isize,
                                px,
                                py,
                            );
                        }
                    }
                    None => {
                        for (slot, component) in components.iter().enumerate() {
                            let source = if plane == 0 { slot } else { 3 };
                            frame.blit_block(*component, px, py, &blocks.data[source]);
                        }
                    }
                }
                blocks_out.insert((plane as u8, index), blocks.as_bytes());
            }

            // FUN_001c0124:84-87 -- between plane passes the reader drops its
            // partial bits and resumes on the next byte boundary.
            br.align_to_next_byte();
        }
    }

    Some(SpiDecoded {
        info: stream.info,
        frame,
        tiles,
        blocks: blocks_out,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_formula_stream_headers() {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&20u32.to_le_bytes());
        bytes.extend_from_slice(&[
            0xaa, 0x01, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05, 0x80, 0x01,
            0x1e, 0x04, 0x00, 0x05, 0x00, 0xe0,
        ]);
        bytes.extend_from_slice(&17u32.to_le_bytes());
        bytes.extend_from_slice(&[
            0xaa, 0x02, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x00, 0x43, 0x02, 0xe0, 0xa0,
            0x2c, 0x00, 0x00,
        ]);

        let stream = parse_stream(&bytes).expect("parse stream");
        assert_eq!(stream.info.width, 1408);
        assert_eq!(stream.info.height, 286);
        assert_eq!(stream.info.tile_cols(), 88);
        assert_eq!(stream.info.tile_rows(), 18);
        assert_eq!(stream.info.rgba_len(), Some(1_610_752));
        assert_eq!(stream.header.color_index, 4);
        assert_eq!(stream.header.tile_rows_hint, 5);
        assert!(stream.header.field_08);
        assert!(stream.header.field_09);
        assert!(stream.header.field_10);
        assert!(!stream.header.field_11);
        assert!(!stream.header.final_reserved_zero);
        assert_eq!(stream.data_header.field_01, 0);
        assert_eq!(stream.data_header.field_06, 0);
        assert_eq!(stream.data_header.field_00, 0);
        assert!(!stream.data_header.field_08);
        assert_eq!(stream.data_header.field_02, 2);
        assert_eq!(stream.data_header.field_03, 24);
        assert_eq!(stream.data_header.field_04, 23);
        assert_eq!(stream.data_header.field_05, 5);
        assert_eq!(stream.payload.len(), 17);
    }

    #[test]
    fn parses_multimath_spi_members() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../samples/MultiMath_260724_201808/note.sdocx");
        if !path.exists() {
            eprintln!("skipping: MultiMath sample not present");
            return;
        }

        let file = std::fs::File::open(path).expect("open sample");
        let mut archive = zip::ZipArchive::new(file).expect("zip sample");
        let mut parsed = Vec::new();
        for i in 0..archive.len() {
            let mut entry = archive.by_index(i).expect("zip entry");
            let name = entry.name().to_string();
            if !name.starts_with("media/") || !name.ends_with(".spi") {
                continue;
            }
            let mut bytes = Vec::new();
            std::io::Read::read_to_end(&mut entry, &mut bytes).expect("read spi");
            let stream = parse_stream(&bytes).unwrap_or_else(|| panic!("parse spi stream: {name}"));
            parsed.push((name, stream.info.width, stream.info.height));
        }

        parsed.sort();
        assert_eq!(parsed.len(), 6);
        assert!(parsed.iter().any(|(name, width, height)| {
            name.contains("@84bbec22-878b-11f1-ad5f-0fcae52b7cba.spi")
                && (*width, *height) == (1408, 286)
        }));
        assert_eq!(
            parsed
                .iter()
                .filter(|(name, _, _)| name.contains("@page_"))
                .count(),
            5
        );
    }

    #[test]
    fn bit_reader_is_msb_first() {
        let mut br = BitReader::new(&[0b1010_0110, 0b0101_0000]);
        assert_eq!(br.read(4), Some(0b1010));
        assert_eq!(br.read(4), Some(0b0110));
        assert_eq!(br.read(4), Some(0b0101));
    }

    #[test]
    fn mode0_motion_matches_native_rules() {
        assert_eq!(mode0_motion(0), (0, 16));
        assert_eq!(mode0_motion(1), (16, 0));
    }

    #[test]
    fn coefficient_tables_sanity() {
        let t = coefficient_tables();
        assert_eq!(t.size_class[0], 0);
        assert_eq!(t.size_class[31], 4);
        assert_eq!(t.mode_to_context[0], 1);
        assert_eq!(t.runlevel[0], (1, 0));
        assert_eq!(t.subblock_mask_short[0], 4);
        assert_eq!(t.quant_group[22], 1);
        assert_eq!(t.quant_group[63], 0);
    }
}
