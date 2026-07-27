#!/usr/bin/env python3
"""The `.spi` / Maetel bitstream: wrapper, chunks, tile modes, payloads.

Mirrors the native bitstream helpers (`FUN_001cc7d4`, `FUN_001ccca4`,
`FUN_001d39fc`) closely enough to consume every syntax element at the exact bit
positions the native decoder does -- verified tile by tile on the whole corpus.
`pysdocx.spi.decode` turns that parse into pixels.

It doubles as a diagnostic CLI (`python -m pysdocx.spi.parse <file> --only …`):
the sequential walk must land exactly on every `AA 02` chunk boundary, which is
the cheapest way to see that a change broke the bit accounting.
"""

from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import struct
import zipfile
from pathlib import Path


class BitReader:
    def __init__(self, data: bytes, bit_pos: int = 0) -> None:
        self.data = data
        self.bit_pos = bit_pos

    def read(self, n: int) -> int:
        if not 0 <= n <= 32:
            raise ValueError(f"invalid bit count {n}")
        if self.bit_pos + n > len(self.data) * 8:
            raise EOFError("bitstream exhausted")
        out = 0
        for _ in range(n):
            byte = self.data[self.bit_pos // 8]
            shift = 7 - (self.bit_pos % 8)
            out = (out << 1) | ((byte >> shift) & 1)
            self.bit_pos += 1
        return out

    def byte_align_like_native(self) -> None:
        # FUN_001ccca4 validates 4 zero bits, then consumes one final zero bit;
        # after that the native bit-buffer continues from the next bit position,
        # not necessarily from a fresh byte boundary.
        pass

    @property
    def byte_pos_floor(self) -> int:
        return self.bit_pos // 8

    @property
    def byte_pos_ceil(self) -> int:
        return (self.bit_pos + 7) // 8

    def align_to_next_byte(self) -> int:
        before = self.bit_pos
        self.bit_pos = self.byte_pos_ceil * 8
        return self.bit_pos - before


@dataclasses.dataclass
class SpiHeader:
    width: int
    height: int
    color_index: int
    tile_rows_hint: int
    flags: tuple[int, int, int, int]


@dataclasses.dataclass
class TileHeader:
    tag_size: int
    field_01: int
    field_06: int
    field_00: int
    field_08: int
    field_02: int
    field_03: int
    field_04: int
    field_05: int
    start_bit: int
    end_bit: int


@dataclasses.dataclass
class TileEvent:
    idx: int
    plane: int
    mode: int
    start_bit: int
    end_bit: int
    note: str
    residual: tuple[int, int] | None = None
    raw_planes: tuple[bytes, bytes, bytes] | None = None


@dataclasses.dataclass
class TileChunk:
    index: int
    offset: int
    header: TileHeader
    rows: int


def split_spi(data: bytes) -> tuple[bytes, bytes]:
    if len(data) < 30:
        raise ValueError("too short")
    header_len = struct.unpack_from("<I", data, 0)[0]
    header = data[4 : 4 + header_len]
    payload_len_off = 4 + header_len
    payload_len = struct.unpack_from("<I", data, payload_len_off)[0]
    payload = data[payload_len_off + 4 : payload_len_off + 4 + payload_len]
    if not header.startswith(b"\xaa\x01"):
        raise ValueError("missing AA 01")
    if not payload.startswith(b"\xaa\x02"):
        raise ValueError("missing AA 02")
    return header, payload


def parse_image_header(stream_from_header_start: bytes) -> SpiHeader:
    if not stream_from_header_start.startswith(b"\xaa\x01"):
        raise ValueError("missing AA 01")
    br = BitReader(stream_from_header_start[6:])
    field_00 = br.read(8)
    field_01 = br.read(16)
    field_02 = br.read(16)
    width = br.read(16)
    height = br.read(16)
    color_index = br.read(8)
    tile_rows_hint = br.read(16)
    field_07 = br.read(8)
    flags = tuple(br.read(1) for _ in range(4))
    reserved = br.read(3)
    final = br.read(1)
    if reserved or final:
        raise ValueError(f"bad image-header tail reserved={reserved} final={final}")
    _ = (field_00, field_01, field_02, field_07)
    return SpiHeader(width, height, color_index, tile_rows_hint, flags)


def parse_tile_header(br: BitReader) -> TileHeader:
    start = br.bit_pos
    magic = br.read(8)
    kind = br.read(8)
    if (magic, kind) != (0xAA, 0x02):
        raise ValueError(f"expected AA 02 at bit {start}, got {magic:02x} {kind:02x}")
    tag_size = br.read(32)  # the chunk's own byte length, header included
    field_01 = br.read(8)
    field_06 = br.read(16)
    field_00 = br.read(8)
    field_08 = br.read(1)
    field_02 = br.read(2)
    field_03 = br.read(8)
    field_04 = br.read(8)
    field_05 = br.read(8)
    reserved = br.read(4)
    final = br.read(1)
    if reserved or final:
        raise ValueError(f"bad tile-header tail at bit {start}: reserved={reserved} final={final}")
    return TileHeader(
        tag_size=tag_size,
        field_01=field_01,
        field_06=field_06,
        field_00=field_00,
        field_08=field_08,
        field_02=field_02,
        field_03=field_03,
        field_04=field_04,
        field_05=field_05,
        start_bit=start,
        end_bit=br.bit_pos,
    )


def find_tile_chunks(payload: bytes, tile_rows: int, tile_rows_hint: int) -> list[TileChunk]:
    """Locate every `AA 02` chunk.

    The chunks are **chained by their own length**: the u32 right after the
    `AA 02` tag is the chunk's byte size, header included, so chunk k+1 starts at
    `offset + tag_size`. Scanning for the tag bytes instead is unsafe -- a raw
    `AA 02` also occurs inside compressed data, and on
    `Machine_learning… media/164@page_0000171.spi` a false positive 7257 bytes
    early passed both the reserved-bit and the `field_06 == index` checks.

    The scan is kept only as a fallback for the chunk that the chain cannot
    reach, and every chunk is still validated by `parse_tile_header`.
    """
    chunks = []
    wanted = (tile_rows + tile_rows_hint - 1) // tile_rows_hint
    magic = bytes([0xAA, 0x02])
    offset = 0
    for index in range(wanted):
        header = None
        if offset < len(payload):
            try:
                header = parse_tile_header(BitReader(payload[offset:]))
            except ValueError:
                header = None
            if header is not None and header.field_06 != index:
                header = None
        if header is None:
            # Chain broken: fall back to scanning from wherever we got to.
            search_from = offset
            while True:
                found = payload.find(magic, search_from)
                if found < 0:
                    raise ValueError(f"missing AA02 chunk {index}")
                try:
                    candidate = parse_tile_header(BitReader(payload[found:]))
                except ValueError:
                    search_from = found + 1
                    continue
                if candidate.field_06 != index:
                    search_from = found + 1
                    continue
                offset, header = found, candidate
                break
        rows_done = index * tile_rows_hint
        rows = min(tile_rows_hint, tile_rows - rows_done)
        chunks.append(TileChunk(index, offset, header, rows))
        offset += header.tag_size
    return chunks


def read_tile_mode(br: BitReader) -> int:
    # FUN_001d39fc: first bit => mode 0, second bit => mode 1, else read two
    # more bits and return 2..5.
    if br.read(1):
        return 0
    if br.read(1):
        return 1
    return br.read(2) + 2


def zigzag_decode_native(code: int) -> int:
    sign = code & 1
    return ((-sign ^ (code >> 1)) + sign)


def read_exp_golomb(br: BitReader) -> int:
    """Unsigned Exp-Golomb, the way FUN_001cd1b4 decodes it.

    The native code does not loop over single bits: it counts leading zeros
    through the byte table at `DAT_001319df` and then pulls that many payload
    bits at once. Bit-for-bit that is the textbook code -- `z` zeros, a `1`, then
    `z` payload bits, so the codeword is `2z + 1` bits long.
    """
    zeros = 0
    while br.read(1) == 0:
        zeros += 1
    payload = br.read(zeros) if zeros else 0
    return (1 << zeros) + payload - 1


# Mode 0 has no coded vector at all: FUN_001cd124 picks the tile above at the
# left edge, otherwise the one to the left (DAT_0012ed78 / DAT_0012ee88).
MOTION_SCALE = 16
MOTION_FROM_ABOVE = (0, 16)
MOTION_FROM_LEFT = (16, 0)


def mode0_motion(tile_x: int) -> tuple[int, int]:
    return MOTION_FROM_ABOVE if tile_x == 0 else MOTION_FROM_LEFT


def read_mode1_residual(br: BitReader) -> tuple[int, int] | None:
    """Motion residual pair for mode 1 (FUN_001cd1b4).

    The handler reads one gate bit and, when it is set, stops there -- the tile
    reuses its predictor unchanged. That is the 1-bit case that dominates the
    native trace. Otherwise two Exp-Golomb codes follow, one per axis, each
    turned into a signed value by the native zig-zag expression.
    """
    if br.read(1):
        return MOTION_FROM_ABOVE
    # The native builds its code as `payload + (1 << z)`, one more than
    # `read_exp_golomb` returns, then zig-zags it; dy is a plain Exp-Golomb.
    # Both are in tiles, scaled to pixels by 16. Verified 2501/2501 against the
    # native vectors, so mode 0 and 1 need no oracle.
    dx = zigzag_decode_native(read_exp_golomb(br) + 1) * MOTION_SCALE
    dy = read_exp_golomb(br) * MOTION_SCALE
    return dx, dy


# FUN_001d4000's "no mode here yet" sentinel. Both neighbours are read through
# it, and it is also one of the two values the short escape can code.
MODE_CONTEXT_EMPTY = 0x11
MODE_CONTEXT_DEFAULT = 2


def decode_mode_with_context(br: BitReader, left: int, above: int) -> int:
    """Port of FUN_001d4000 -- the tree B mode coder, plane 1 mode 3.

    Context-modelled against the two already-decoded neighbours (the block to
    the left and the one above), each read through the `0x11 -> 2` mapping:

        1        predict from a neighbour; when the two agree that is all
        1 0      ...they disagree, so one bit picks: 0 = left, 1 = above
        0 1 b    short escape, coding exactly 2 or 0x11
        0 0 vvvv explicit 4-bit value, biased past whatever context predicted

    Verified call-for-call against `--context-trace`: 2199 calls, every one
    matching on both bit count and decoded value.
    """
    left = MODE_CONTEXT_DEFAULT if left == MODE_CONTEXT_EMPTY else left
    above = MODE_CONTEXT_DEFAULT if above == MODE_CONTEXT_EMPTY else above

    if br.read(1):
        if left == above:
            return left
        return above if br.read(1) else left

    if br.read(1):
        return MODE_CONTEXT_EMPTY if br.read(1) else MODE_CONTEXT_DEFAULT

    value = br.read(4)
    # Skip the values the context already predicts, so the explicit code never
    # spends a symbol on something the cheaper branches could have said.
    if value > 1 or left <= value:
        value += 1
    if value > 1 and left != MODE_CONTEXT_DEFAULT and left <= value:
        value += 1
    return value & 0xFF


class ModeMap:
    """The intra-mode map FUN_001d4000 predicts from, at 4-pixel granularity.

    Each 16-pixel tile covers 4x4 entries; each `FUN_001d2874` call owns one 2x2
    quadrant of that, and within a call the (up to four) modes take one entry
    each. An unsplit call writes its single mode across the whole quadrant.

    Deriving this is what lets the decoder stand on its own: the map is built
    purely from decoded modes, with no pixel reconstruction involved, so the
    `--context-csv` oracle is no longer needed.

    The one non-obvious rule: **the map does not carry across AA02 chunks**. A
    chunk restarts the native line buffers, so the first tile row of a chunk has
    nothing above it. Without that, 126 of 2199 contexts come out wrong and the
    stream desyncs.

    The map is **per band**, not per plane: `--context-trace` carries a `band`
    column, 0/1/2 for plane 0's three colour components and 3 for the alpha.
    Sharing one map across a plane's three components gets 17/19 of the contexts
    on the page-59 sample and desyncs on the rest.
    """

    ENTRIES_PER_TILE = 4
    BANDS = 4

    def __init__(self, tile_cols: int, tile_rows: int):
        self.width = tile_cols * self.ENTRIES_PER_TILE
        self.height = tile_rows * self.ENTRIES_PER_TILE
        self.cells = [
            [[MODE_CONTEXT_DEFAULT] * self.width for _ in range(self.height)]
            for _ in range(self.BANDS)
        ]

    def quadrant(self, tile_x: int, tile_y: int, sub: int) -> tuple[int, int]:
        """Top-left entry of the quadrant a FUN_001d2874 call writes."""
        col = tile_x * self.ENTRIES_PER_TILE + (sub & 1) * 2
        row = tile_y * self.ENTRIES_PER_TILE + (2 if sub >= 2 else 0)
        return col, row

    def context(
        self, col: int, row: int, tile_y: int, chunk_first_row: bool, band: int = 3
    ) -> tuple[int, int]:
        cells = self.cells[band]
        left = cells[row][col - 1] if col > 0 else MODE_CONTEXT_DEFAULT
        top_row = tile_y * self.ENTRIES_PER_TILE
        if (chunk_first_row and row == top_row) or row == 0:
            above = MODE_CONTEXT_DEFAULT
        else:
            above = cells[row - 1][col]
        return left, above

    def set(self, col: int, row: int, mode: int, split: bool, band: int = 3, span: int = 2) -> None:
        """Write a decoded mode back.

        `span` is how many entries on a side the block covers: 1 for a split 4x4,
        2 for an 8x8, 4 for the unsplit 16x16 plane 0 mode 3 uses. Writing a 16x16
        as 2x2 leaves the neighbours stale and costs contexts downstream.
        """
        cells = self.cells[band]
        if split:
            cells[row][col] = mode
            return
        for dr in range(span):
            for dc in range(span):
                cells[row + dr][col + dc] = mode


_COEFF_TABLES: dict | None = None


def coefficient_tables() -> dict:
    """The FUN_001d2874 lookup tables, read from the .so and cached."""
    global _COEFF_TABLES
    if _COEFF_TABLES is None:
        from pysdocx.spi import tables

        _COEFF_TABLES = tables.load_coefficient_tables()
    return _COEFF_TABLES


# The escape in the run/level code kicks in past this prefix length; below it,
# the value indexes the static (level, run) table instead.
RUNLEVEL_ESCAPE_PREFIX = 6
RUNLEVEL_ESCAPE_BIAS = 0x80

# FUN_001d0044 always issues exactly four FUN_001d2874 calls per tile (band 3,
# sub-blocks 0..3) -- uniform across all 327 mode-3 tiles in the corpus.
COEFF_BLOCKS_PER_TILE = 4

# tile[0x38] on plane 0's colour bands, from the FUN_001d2874 entry trace.
PLANE0_QUANT = 23


def read_biased_value(br: BitReader, zeros: int) -> int:
    """`zeros` payload bits read as `value + 2**zeros`.

    Not the same code as `read_exp_golomb`, which biases by `2**z - 1`. Both
    appear in this decoder, a few lines apart, so they are kept distinct rather
    than folded together.
    """
    payload = 0
    for _ in range(zeros):
        payload = (payload << 1) | br.read(1)
    return payload + (1 << zeros)


def decode_coefficient_block(
    br: BitReader,
    mode_contexts,
    *,
    split_enabled: int = 1,
    dim_code: int = 8,
    quant: int = 0,
    mode_map: "ModeMap | None" = None,
    tile_x: int = 0,
    tile_y: int = 0,
    sub: int = 0,
    band: int = 3,
    chunk_first_row: bool = False,
    out: dict | None = None,
) -> None:
    """Port of FUN_001d2874 -- the tree B coefficient decoder, plane 1 mode 3.

        1 bit       split; halves the block, from 8x8 to 4x4
        n modes     FUN_001d4000 per sub-block, n = 1 unsplit, 4 split
        prefix      selects a sub-block presence mask from a static table
        per present sub-block:
            count   how many (run, level) pairs follow, biased by 2**z
            pairs   prefix z, then z+1 bits whose last bit is the sign;
                    z <= 6 indexes the static (level, run) table, above that
                    run and level are packed either side of `size_class * 2`

    `mode_contexts` yields the (left, above) pair for each FUN_001d4000 call.
    Those come from decoder state that only pixel reconstruction maintains, so
    they are supplied by `--context-trace` rather than derived; everything else
    here is read from the bitstream.
    """
    tables = coefficient_tables()

    split = br.read(1) if split_enabled else 0
    block_dim = dim_code >> split
    size_class = tables["size_class"][block_dim]
    n_modes = (split + 1) << split

    modes = []
    if mode_map is not None:
        col0, row0 = mode_map.quadrant(tile_x, tile_y, sub)
    span = 4 if block_dim == 0x10 else 2
    for k in range(n_modes):
        if mode_map is not None:
            col, row = col0 + (k & 1), row0 + (k >> 1)
            left, above = mode_map.context(col, row, tile_y, chunk_first_row, band)
        else:
            left, above = next(mode_contexts)
        mode = decode_mode_with_context(br, left, above)
        modes.append(mode)
        if mode_map is not None:
            mode_map.set(col, row, mode, split=bool(split), band=band, span=span)

    zeros = read_unary_prefix(br)
    if block_dim != 4:
        if zeros > 7:
            raise IllegalMode(f"sub-block mask prefix {zeros} out of range")
        mask = tables["subblock_mask_short"][zeros]
    else:
        if quant > 0x33:
            raise IllegalMode(f"quant level {quant} out of range")
        group = tables["quant_group"][quant] * 0x40
        if zeros == 0:
            mask = tables["subblock_mask_long"][group]
        else:
            value = br.read(zeros) + (1 << zeros) - 1
            if value > 0x3F:
                raise IllegalMode(f"sub-block mask index {value} out of range")
            mask = tables["subblock_mask_long"][group + value]

    block_out = None
    if out is not None:
        block_out = {
            "band": band,
            "sub": sub,
            "split": split,
            "block_dim": block_dim,
            "size_class": size_class,
            "modes": modes[:],
            "mask": mask,
            # Reconstruction needs the quant twice over: here it picked which half
            # of the sub-block mask table to read, and FUN_001d31b8 indexes the
            # dequantisation tables with the same byte (tile[0x3a]).
            "quant": quant,
            # `tile[0x31] == 2` selects the second group of 4x4/8x8 dequant
            # matrices. It is 1 on every traced call, so group 0 is what the
            # corpus exercises; group 1 stays untested rather than assumed.
            "quant_group": 0,
            "subblocks": [],
        }
        out.setdefault("mode3_blocks", []).append(block_out)

    # There are TWO coefficient decoders, and which one runs is decided by the
    # quant. In FUN_001d2874:
    #
    #     if (*(char *)(param_1 + 7) == '\0')  ... the inline run/level loop ...
    #     else  FUN_001d42a8(bitreader, scan_ctx0, buffer, dim, &flag);
    #
    # `param_1` is `undefined8 *`, so `param_1 + 7` is **tile[0x38]**, the quant
    # -- the 8-byte-unit trap again, for the third time in this decoder (see
    # SPI-HANDOFF 8.5). It is 0 on the alpha plane and 23 on plane 0's colour
    # bands, so plane 0 has never used the inline loop.
    #
    # The two share their bit syntax exactly -- same unary prefix, same
    # `zeros + 1` payload bits, same `value`, same 0x7f bound, same flag rule,
    # same position accumulation -- which is why bit counts stayed exact while
    # the reconstruction was wrong on 11 of 61 blocks.
    escape_decoder = quant != 0
    for i in range(n_modes):
        if not (mask >> ((n_modes + 1) - i)) & 1:
            continue  # sub-block carries no coefficients
        if escape_decoder:
            # The caller dereferences the *first* of the three scan pointers of
            # the size class (`*(undefined8 *)(&DAT_0020a1a0 + tile[0x1f]*0x18)`)
            # and FUN_001d42a8 indexes it directly, so context 0 always. That
            # table is the same one PTR_DAT_00204b08 points at.
            context = 0
        elif block_dim == 0x10 or modes[i] == MODE_CONTEXT_EMPTY:
            context = 0
        else:
            context = tables["mode_to_context"][modes[i]]
        scan = tables["scans"].get((size_class, context))
        if scan is None:
            raise IllegalMode(f"no scan order for size class {size_class} context {context}")

        count = read_biased_value(br, read_unary_prefix(br))
        if count > block_dim * block_dim:
            raise IllegalMode(f"{count} coefficients exceeds a {block_dim}x{block_dim} block")

        position = 0
        coeffs = []
        for _ in range(count):
            zeros = read_unary_prefix(br)
            bits = 0
            for _ in range(zeros + 1):
                bits = (bits << 1) | br.read(1)
            value = (1 << zeros) + (bits >> 1)
            if zeros > RUNLEVEL_ESCAPE_PREFIX:
                if escape_decoder:
                    # FUN_001d42a8: bias 1 (not 0x80), a fixed 8-bit run field
                    # (not size_class * 2), and level **minus** one.
                    run = (value - 1) & 0xFF
                    level = ((value - 1) >> 8) - 1
                else:
                    shift = size_class * 2
                    run = (value - RUNLEVEL_ESCAPE_BIAS) & ((1 << shift) - 1)
                    level = ((value - RUNLEVEL_ESCAPE_BIAS) >> shift) + 1
            else:
                if value > 0x7F:
                    raise IllegalMode(f"run/level index {value} out of range")
                level, run = tables["runlevel"][value - 1]
            signed_level = -level if (bits & 1) else level
            position += run + 1
            coeffs.append((position - 1, signed_level))
        if block_out is not None:
            block_out["subblocks"].append(
                {
                    "index": i,
                    "mode": modes[i],
                    "context": context,
                    "scan_len": len(scan),
                    "coeffs": coeffs,
                }
            )


class IllegalMode(Exception):
    """A (plane, mode) pair the native decoder rejects outright.

    `PTR_FUN_0020c418[1 * 6 + 2]` and `[1 * 6 + 4]` both point at FUN_001cef00,
    whose entire body is `return 0xffffff36`. So modes 2 and 4 simply cannot
    occur on plane 1: seeing one means the bit position is wrong, several tiles
    back. This is a free desync detector -- no ground truth needed.
    """


class UnportedHandler(Exception):
    """A handler whose real bit consumption has not been ported yet.

    Raised instead of guessing, so that a walk which "succeeds" really did read
    every bit the way the native decoder does.
    """


def read_unary_prefix(br: BitReader) -> int:
    """Count leading zeros, consuming them and the terminating 1.

    The native code never loops over single bits: it peeks 32 bits and counts
    leading zeros through the byte table at `DAT_001319df`. That table is
    verified to be plain `clz8` (t[0]=8, t[1]=7, t[2:4]=6, ... t[128:]=0), so
    bit-for-bit this is the same thing.
    """
    zeros = 0
    while br.read(1) == 0:
        zeros += 1
    return zeros


# Above this many leading zeros the symbol code escapes instead of continuing.
SYMBOL_ESCAPE_PREFIX = 0x15
# The three symbol values the escape encodes directly, before it gives up and
# spells out a literal byte.
SYMBOL_ESCAPE_BASE = 0x54


def read_block_symbol(br: BitReader) -> int:
    """One symbol of a FUN_001d3b4c block.

    `z` leading zeros, a `1`, then two payload bits `v`:

        z < 21          symbol = z * 4 + v          (covers 0..83)
        z >= 21, v <= 2 symbol = 0x54 | v           (84..86)
        z >= 21, v == 3 symbol = the next 8 bits    (literal escape)
    """
    zeros = read_unary_prefix(br)
    v = br.read(2)
    if zeros < SYMBOL_ESCAPE_PREFIX:
        return zeros * 4 + v
    if v > 2:
        return br.read(8)
    return SYMBOL_ESCAPE_BASE | v


def decode_symbol_block(br: BitReader, count: int = 0x100) -> bytearray:
    """Port of FUN_001d3b4c: run-length + Exp-Golomb symbol block.

    A run length is coded only when the two previously decoded symbols were
    equal -- then the run repeats that value. The native code carries the
    comparison through two registers (`uVar7` lagging `uVar11` by one symbol),
    including the quirk that both start from 0 while the comparator starts at
    0xff, so the first possible run is at the second symbol. Reproduced as-is
    rather than tidied, because the bit count depends on it.
    """
    out = bytearray()
    cur = 0
    cmp_prev = 0xFF
    while True:
        prev = cur
        if (prev & 0xFF) == (cmp_prev & 0xFF):
            run = read_exp_golomb(br) & 0xFF
            if run:
                out.extend(bytes([cmp_prev & 0xFF]) * run)
        sym = read_block_symbol(br)
        out.append(sym & 0xFF)
        cur = sym
        cmp_prev = prev
        if len(out) >= count:
            return out


PALETTE_PIXELS = 0x100  # a 16x16 tile
PALETTE_MAX_ENTRIES = 0x100


def decode_palette_indices(br: BitReader, index_width: int) -> list[int]:
    """The index run-loop at the tail of FUN_001cf238.

    Pairs of (index, run) until the tile's 256 pixels are covered: an index of
    `index_width` bits, then an Exp-Golomb run saying how many *extra* pixels
    repeat it. The native code bails out with 0xffffff36 if a run would overflow
    the tile, which is reproduced -- overflowing means the bit position is wrong.
    """
    out: list[int] = []
    while len(out) < PALETTE_PIXELS:
        index = br.read(index_width)
        run = read_exp_golomb(br)
        if run + len(out) > 0xFF:
            raise IllegalMode(
                f"palette run {run} at pixel {len(out)} overflows the tile; "
                "the bit position must already be wrong"
            )
        out.extend([index] * (run + 1))
    return out


PALETTE_BYTES = 0x300  # 256 entries x RGB


@dataclasses.dataclass
class PaletteState:
    """Mode 4's palette, which is transmitted incrementally across tiles.

    `entries` and `index_width` mirror tile[0x9c4] / tile[0x9c8]; `palette` is
    the running RGB table at tile[0x9cc] that later tiles append to instead of
    resending.
    """

    entries: int = 0
    index_width: int = 0
    palette: bytearray = dataclasses.field(
        default_factory=lambda: bytearray(PALETTE_BYTES)
    )
    #: the tile just decoded -- 256 palette indices, or None for a flat tile
    indices: list[int] | None = None


def consume_mode4_palette(
    br: BitReader,
    prev_palette_entries: int,
    prev_index_width: int,
    state: PaletteState | None = None,
) -> tuple[str, int, int]:
    """Port of the FUN_001cf238 palette path -- plane 0 mode 4.

    Layout, in order:

        1 bit   palette update? 0 = carry the previous palette over verbatim
        1 bit   fresh: 0 appends to the running palette, 1 starts a new one
        4 bits  index_width; 0 means the whole tile is one flat colour
        w bits  entry count - 1                       (only when index_width > 0)
        n*3 B   the palette entries not already carried over
        3 B     the flat colour                       (only when index_width = 0)
        ...     then the index run-loop, unless index_width is 0

    `prev_palette_entries` and `prev_index_width` are the decoder state at
    tile[0x9c4] / tile[0x9c8]; a tile that carries its palette over reads
    nothing but the leading bit and its indices, which is why they have to be
    supplied when a handler is verified in isolation.

    Returns the note plus the updated (entries, index_width), which the caller
    has to carry into the next tile -- a sequential walk desyncs without it even
    though every handler is individually bit-exact.

    When `state` is given the palette bytes and pixel indices are recorded into
    it as well, which is what reconstruction needs; the bits read are identical
    either way.
    """
    if not br.read(1):
        # Carried over wholesale: entry count and index width both stay put.
        if prev_index_width == 0:
            if state is not None:
                state.indices = None  # flat: the whole tile is palette entry 0
            return "exact:mode4-carry-flat", prev_palette_entries, prev_index_width
        indices = decode_palette_indices(br, prev_index_width)
        if state is not None:
            state.indices = indices
        return (
            f"exact:mode4-carry-indices w={prev_index_width} n={len(indices)}",
            prev_palette_entries,
            prev_index_width,
        )

    fresh = br.read(1)
    index_width = br.read(4)
    # A fresh palette is built from scratch; otherwise the entries already
    # carried over are kept and only the new tail is transmitted.
    already = 0 if fresh else prev_palette_entries * 3

    if index_width == 0:
        flat = [br.read(8) for _ in range(3)]  # one RGB triplet; fills the tile
        if state is not None:
            state.palette[0:3] = bytes(flat)
            state.indices = None
        # FUN_001cf238 leaves `fresh` itself in tile[0x9c4] on this path -- odd,
        # but the next tile's palette arithmetic depends on it.
        return "exact:mode4-flat-colour", fresh, 0

    entries = br.read(index_width) + 1
    if entries > PALETTE_MAX_ENTRIES:
        raise IllegalMode(
            f"palette of {entries} entries exceeds {PALETTE_MAX_ENTRIES}; "
            "the bit position must already be wrong"
        )
    for offset in range(already, max(entries * 3, already)):
        byte = br.read(8)
        if state is not None and offset < PALETTE_BYTES:
            state.palette[offset] = byte
    indices = decode_palette_indices(br, index_width)
    if state is not None:
        state.indices = indices
    return (
        f"exact:mode4-palette entries={entries} w={index_width} n={len(indices)}",
        entries,
        index_width,
    )


# (mode, plane) pairs whose bit consumption is derived from the decompiled
# handler and believed exact -- not calibrated, not guessed.
#
#   mode 0, both planes -- FUN_001cd124 touches only decoder state, reads nothing.
#   mode 5, both planes -- FUN_001cee5c / FUN_001cf19c call FUN_001d20d8, whose
#           unrolled loop writes exactly 0x100 bytes (`lVar5 += 0x10`, exit at
#           0x100): three blocks on plane 0, one on plane 1.
#   mode 1, both planes -- FUN_001cd1b4 reads a gate bit, then two Exp-Golomb
#           codes when it is clear. Verified against the native trace.
#   mode 2, plane 0     -- FUN_001cdddc reads one bit into tile[0x9bd], then
#           FUN_001cf238. With that bit clear (the only case in the corpus) the
#           handler decodes three FUN_001d3b4c blocks, one per colour component.
STRICT_PORTED = {(0, 0), (0, 1), (1, 0), (1, 1), (5, 0), (5, 1), (2, 0), (4, 0), (3, 0), (3, 1)}

# Everything else: the coefficient-decoder modes. The note names the real native
# handler and the bit range it consumes in the native trace, so the size of the
# remaining gap is visible at the point of failure rather than buried in docs.
UNPORTED_HANDLERS: dict[tuple[int, int], str] = {}


def consume_known_mode_payload(
    br: BitReader,
    mode: int,
    plane: int = 0,
    mode5_blocks: list[tuple[int, bytes, bytes, bytes]] | None = None,
    tile_idx: int | None = None,
    strict: bool = True,
    state: dict | None = None,
) -> tuple[str, tuple[int, int] | None, tuple[bytes, bytes, bytes] | None]:
    """Consume the payload bits of one tile.

    This deliberately models bit consumption, not pixel reconstruction. With
    `strict=True` (the default) only handlers in `STRICT_PORTED` run; anything
    else raises `UnportedHandler` rather than inventing a bit count.
    """
    # Checked before anything else: the native table has no handler here.
    if plane == 1 and mode in (2, 4):
        raise IllegalMode(
            f"mode {mode} on plane 1 maps to FUN_001cef00 (return 0xffffff36); "
            "the bitstream position must already be wrong"
        )

    if mode == 0:
        # FUN_001cd124: writes flags and a constant into the tile struct only.
        return "exact:mode0-no-bits", None, None

    if mode == 1:
        residual = read_mode1_residual(br)
        return f"exact:mode1-motion={residual}", residual, None

    if mode == 2 and plane == 0:
        # FUN_001cdddc: one bit, stored in tile[0x9bd]. Set means FUN_001cf238
        # takes its single-block branch (plus FUN_001d4a28 twice); clear means
        # three symbol blocks, one per colour component. Only the clear case
        # occurs in the corpus -- FUN_001d4a28 never executes -- so the set case
        # is refused rather than guessed.
        if br.read(1):
            raise UnportedHandler(
                "plane 0 mode 2 with tile[0x9bd] set: FUN_001cf238 single-block "
                "branch + FUN_001d4a28, never exercised by the corpus"
            )
        blocks = [decode_symbol_block(br) for _ in range(3)]
        if state is not None:
            state["symbol_blocks"] = blocks
        return f"exact:mode2-3x{len(blocks[0])}-symbol-blocks", None, None

    if mode == 4 and plane == 0:
        # FUN_001cedf4 clears tile[0x9bd] without reading, so FUN_001cf238
        # always takes its palette path here.
        st = state if state is not None else {}
        note, entries, index_width = consume_mode4_palette(
            br,
            st.get("state_pal_count", 0),
            st.get("state_index_width", 0),
        )
        # Written back so a sequential walk carries the palette forward.
        st["state_pal_count"] = entries
        st["state_index_width"] = index_width
        return note, None, None

    if mode == 3:
        st = state or {}
        contexts = st.get("mode_contexts")
        mode_map = st.get("mode_map")
        if contexts is None and mode_map is None:
            raise UnportedHandler(
                "mode 3 needs neighbour contexts: either a ModeMap in "
                "state['mode_map'] or the --context-csv oracle"
            )
        # FUN_001cef0c (plane 1) reads a 2-bit sub-mode only when tile[8] is 1,
        # which does not happen anywhere in the corpus: the element trace shows 0
        # bits between the handler entry and FUN_001d0044 on all 327 tiles. The
        # branch is therefore left unported rather than guessed.
        # FUN_001ce290's own bit (the plane 1 wrapper has none). It picks which of
        # the chunk header's **two** quantiser fields the tile uses:
        #
        #     bit 0 -> field_03      bit 1 -> field_04
        #
        # Every corpus member carries (field_03, field_04) = (24, 23), so a tile
        # is quantised at 24 or at 23. basic-18 and page-59 happen to have the bit
        # set on every mode-3 tile, which is why a hardcoded 23 worked there;
        # Allsamsungnotes page 7 mixes both and pins the rule at **1409/1409**
        # tiles against the native `tile[0x3a]`.
        quant_select = br.read(1) if plane == 0 else 0
        st["mode3_blocks"] = []
        # FUN_001d0044 walks the plane's bands -- three colour components on
        # plane 0, one alpha on plane 1 -- and reads one bit per band: set means
        # the tile splits into four 8x8 quadrants (each of which may split again
        # to 4x4), clear means a single unsplit 16x16 block.
        bands = (0, 1, 2) if plane == 0 else (3,)
        # The quant is used twice: here it picks which half of the sub-block mask
        # table a 4x4 block reads, and FUN_001d31b8 indexes the dequantisation
        # tables with the same byte (tile[0x3a]).
        if plane == 0:
            quant = st.get("quant_field_04" if quant_select else "quant_field_03",
                           PLANE0_QUANT)
        else:
            quant = 0
        for band in bands:
            if br.read(1):
                blocks = [(sub, 1, 8) for sub in range(COEFF_BLOCKS_PER_TILE)]
            else:
                blocks = [(0, 0, 0x10)]
            for sub, split_enabled, dim_code in blocks:
                decode_coefficient_block(
                    br,
                    contexts,
                    split_enabled=split_enabled,
                    dim_code=dim_code,
                    quant=quant,
                    mode_map=mode_map,
                    tile_x=st.get("tile_x", 0),
                    tile_y=st.get("tile_y", 0),
                    sub=sub,
                    band=band,
                    chunk_first_row=st.get("chunk_first_row", False),
                    out=st,
                )
        return f"exact:mode3-{len(st['mode3_blocks'])}-coefficient-blocks", None, None

    if mode == 5:
        # FUN_001cee5c / FUN_001cf19c both rewind to a byte boundary first
        # (ptr -= count>>3; bits = count = 0) before pulling whole bytes.
        skipped = br.align_to_next_byte()
        block_count = 1 if plane == 1 else 3
        planes = []
        for _ in range(block_count):
            planes.append(bytes(br.read(8) for _ in range(256)))
        while len(planes) < 3:
            planes.append(bytes([0x80] * 256))
        if mode5_blocks is not None and tile_idx is not None:
            mode5_blocks.append((tile_idx, planes[0], planes[1], planes[2]))
        raw = (planes[0], planes[1], planes[2])
        return (
            f"exact:plane{plane}-mode5-raw={block_count * 256}B align_bits={skipped}",
            None,
            raw,
        )

    if strict:
        raise UnportedHandler(
            f"plane {plane} mode {mode}: {UNPORTED_HANDLERS.get((mode, plane), 'unknown handler')}"
        )

    # --- everything below is a GUESS, kept only for --guess exploration ---
    if mode == 4:
        return "guess:mode4-no-extra-bits", None, None
    if mode == 2:
        flag = br.read(1)
        return f"guess:mode2-predictor-flag={flag}", None, None
    if mode == 3:
        if plane == 1:
            return "guess:plane1-mode3-no-direct-bits", None, None
        flag = br.read(1)
        return f"guess:mode3-submode-flag={flag}", None, None
    if mode == 1:
        dx = read_mode1_residual(br)
        dy = read_mode1_residual(br)
        residual = (dx * 16, dy * 16)
        return f"guess:mode1-residuals={residual}", residual, None
    raise NotImplementedError(f"mode {mode} payload consumption not ported")


def iter_member_bytes(path: Path):
    if path.suffix == ".sdocx":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.startswith("media/") and name.endswith(".spi"):
                    yield name, zf.read(name)
    else:
        yield path.name, path.read_bytes()


def format_modes(modes: list[int]) -> str:
    if len(modes) <= 96:
        return repr(modes)
    return f"{modes[:48]} ... {modes[-24:]}"


def write_mode_map(path: Path, modes: list[int], tile_cols: int, tile_rows: int) -> None:
    from PIL import Image, ImageDraw

    scale = 8
    palette = {
        0: (245, 245, 238),
        1: (228, 90, 54),
        2: (74, 130, 180),
        3: (67, 160, 112),
        4: (235, 190, 65),
        5: (40, 45, 50),
    }
    img = Image.new("RGB", (tile_cols * scale, tile_rows * scale), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for idx, mode in enumerate(modes[: tile_cols * tile_rows]):
        x = (idx % tile_cols) * scale
        y = (idx // tile_cols) * scale
        draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=palette[mode])
    img.save(path)


def write_mode5_y_map(
    path: Path,
    mode5_blocks: list[tuple[int, bytes, bytes, bytes]],
    tile_cols: int,
    tile_rows: int,
) -> None:
    from PIL import Image

    img = Image.new("L", (tile_cols * 16, tile_rows * 16), 255)
    for idx, plane0, _plane1, _plane2 in mode5_blocks:
        x0 = (idx % tile_cols) * 16
        y0 = (idx // tile_cols) * 16
        tile = Image.frombytes("L", (16, 16), plane0)
        img.paste(tile, (x0, y0))
    img.save(path)


def paste_block(plane: bytearray, stride: int, x: int, y: int, block: bytes) -> None:
    for row in range(16):
        dst = (y + row) * stride + x
        plane[dst : dst + 16] = block[row * 16 : row * 16 + 16]


def copy_block(plane: bytearray, stride: int, src_x: int, src_y: int, dst_x: int, dst_y: int) -> None:
    if src_x < 0 or src_y < 0 or src_x + 16 > stride or src_y + 16 > len(plane) // stride:
        return
    for row in range(16):
        src = (src_y + row) * stride + src_x
        dst = (dst_y + row) * stride + dst_x
        plane[dst : dst + 16] = plane[src : src + 16]


def blend_neighbor_block(plane: bytearray, stride: int, x: int, y: int) -> bytes:
    out = bytearray([0x80] * 256)
    for row in range(16):
        for col in range(16):
            vals = []
            if x > 0:
                vals.append(plane[(y + row) * stride + x + col - 16])
            if y > 0:
                vals.append(plane[(y + row - 16) * stride + x + col])
            out[row * 16 + col] = sum(vals) // len(vals) if vals else 0x80
    return bytes(out)


def write_stateful_preview(
    path: Path,
    events: list[TileEvent],
    width: int,
    height: int,
    tile_cols: int,
    tile_rows: int,
) -> None:
    from PIL import Image

    padded_width = tile_cols * 16
    padded_height = tile_rows * 16
    planes = [bytearray([0x80] * (padded_width * padded_height)) for _ in range(3)]
    for event in events:
        if event.plane != 0:
            continue
        x = (event.idx % tile_cols) * 16
        y = (event.idx // tile_cols) * 16
        if event.raw_planes is not None:
            for plane, raw in zip(planes, event.raw_planes, strict=True):
                paste_block(plane, padded_width, x, y, raw)
            continue
        if event.mode == 0:
            src_x, src_y = (x - 16, y) if x else (x, y - 16)
            for plane in planes:
                copy_block(plane, padded_width, src_x, src_y, x, y)
            continue
        if event.mode == 1 and event.residual is not None:
            dx, dy = event.residual
            for plane in planes:
                copy_block(plane, padded_width, x - dx, y - dy, x, y)
            continue
        for plane in planes:
            paste_block(plane, padded_width, x, y, blend_neighbor_block(plane, padded_width, x, y))

    rgb = Image.merge(
        "RGB",
        [Image.frombytes("L", (padded_width, padded_height), bytes(plane)) for plane in planes],
    )
    rgb.crop((0, 0, width, height)).save(path)


def load_mode_contexts(path: Path) -> dict[int, object]:
    """Per-tile FUN_001d4000 neighbour contexts, keyed by linear tile index.

    The trace interleaves the bands of a tile in the order the decoder visits
    them -- 0/1/2 for plane 0's colour components, 3 for the alpha -- but the two
    planes are separate passes over the whole image, so the rows for band 3
    arrive long after the colour ones. Replaying a tile in isolation therefore
    needs them regrouped per (tile, band) and concatenated in band order, not in
    file order.

    Needed only for `--verify-handlers`; the sequential walk derives its own
    contexts from the `ModeMap`.
    """
    grouped: dict[tuple[int, int], list[tuple[int, int]]] = collections.defaultdict(list)
    with path.open() as f:
        for row in csv.DictReader(f):
            key = (int(row["tile_idx"]), int(row.get("band", 3)))
            grouped[key].append((int(row["left"]), int(row["above"])))

    by_tile: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    for (tile, _band), pairs in sorted(grouped.items()):
        by_tile[tile].extend(pairs)
    return {k: iter(v) for k, v in by_tile.items()}


def verify_handlers(
    name: str, data: bytes, trace_path: Path, show: int,
    context_path: Path | None = None,
) -> bool:
    """Check each ported handler against the native per-tile trace, in isolation.

    `spi_emu.py --trace-csv` records, for every tile, the bit position right
    after the mode VLC and right after the payload. So a handler can be checked
    on its own -- seek to the recorded start, run it, compare the bit count --
    without needing a complete walk of the stream. That means progress is
    measurable one handler at a time, instead of all-or-nothing.
    """
    _header, payload = split_spi(data)
    with trace_path.open() as f:
        rows = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(f)]

    # Mode 3 branches on neighbour modes that only a full walk maintains, so in
    # isolation those come from the native context trace. `load_mode_contexts`
    # regroups it per band, which is what a replayed tile consumes in order.
    context_iters = load_mode_contexts(context_path) if context_path is not None else {}

    stats: dict[tuple[int, int], dict] = {}
    for row in rows:
        key = (row["plane"], row["mode"])
        st = stats.setdefault(key, {"n": 0, "ok": 0, "bad": 0, "unported": 0, "examples": []})
        st["n"] += 1
        start = row["payload_start_bit"]
        if start < 0:
            st["unported"] += 1
            continue
        br = BitReader(payload, start)
        try:
            state = dict(row)
            if row["mode"] == 3:
                state["mode_contexts"] = context_iters.get(row["tile_idx"])
            consume_known_mode_payload(
                br, row["mode"], row["plane"], strict=True, state=state
            )
        except UnportedHandler:
            st["unported"] += 1
            continue
        except (IllegalMode, EOFError, NotImplementedError) as exc:
            st["bad"] += 1
            if len(st["examples"]) < 3:
                st["examples"].append(f"tile {row['tile_idx']}: {type(exc).__name__}: {exc}")
            continue
        got = br.bit_pos - start
        want = row["payload_bits"]
        if got == want:
            st["ok"] += 1
        else:
            st["bad"] += 1
            if len(st["examples"]) < 3:
                st["examples"].append(
                    f"tile {row['tile_idx']} (x={row['x_tile']},y={row['y_tile']}) "
                    f"consumed {got} bits, native consumed {want}"
                )

    print(f"\n{name}")
    print(f"  verifying against {trace_path} ({len(rows)} tiles)")
    print("  plane mode   tiles      ok     bad  unported   status")
    total_ok = total = 0
    for (plane, mode), st in sorted(stats.items()):
        if st["unported"] == st["n"]:
            status = "NOT PORTED"
        elif st["bad"] == 0 and st["unported"] == 0:
            status = "EXACT"
        else:
            status = "MISMATCH"
        print(
            f"    {plane}    {mode}  {st['n']:6d}  {st['ok']:6d}  {st['bad']:6d}  "
            f"{st['unported']:8d}   {status}"
        )
        total_ok += st["ok"]
        total += st["n"]
        for ex in st["examples"][:show]:
            print(f"        e.g. {ex}")
    print(f"  TOTAL: {total_ok}/{total} tiles reproduce the native bit count exactly")
    return total_ok == total


def plane_count_for(color_index: int) -> tuple[int, dict | None]:
    """How many plane passes a `color_index` implies, per FUN_001c0608:174-181.

    Falls back to 1 plane if the native library is not reachable, so the probe
    still runs off-box -- but says so.
    """
    from pysdocx.spi import tables

    info = tables.FORMATS.get(color_index)
    if info is None:
        return 1, None
    return info["plane_count"], info


def walk_chunk(
    chunk: TileChunk,
    payload: bytes,
    tile_cols: int,
    tile_rows_hint: int,
    planes: int,
    max_tiles: int,
    strict: bool,
    events: list,
    mode5_blocks: list,
    contexts: dict[int, object] | None = None,
    plane_state: list[dict] | None = None,
    intra_modes: "ModeMap | None" = None,
) -> tuple[int, str | None]:
    """Decode one AA02 chunk: `planes` full passes over its tile rows.

    Returns (end_byte_within_payload, stop_reason). `stop_reason` is None when
    every tile of every plane was consumed.
    """
    br = BitReader(payload[chunk.offset :])
    parse_tile_header(br)
    chunk_tile_count = tile_cols * chunk.rows
    # Decoder state that survives from tile to tile within a plane pass. Only
    # mode 4's palette uses it so far, but it desyncs the whole walk without it.
    if plane_state is None:
        plane_state = [{} for _ in range(planes)]

    for plane in range(planes):
        for local_idx in range(chunk_tile_count):
            global_idx = chunk.index * tile_rows_hint * tile_cols + local_idx
            if len(events) >= max_tiles:
                return chunk.offset + br.byte_pos_ceil, "max-tiles reached"
            try:
                mode = read_tile_mode(br)
                before = chunk.offset * 8 + br.bit_pos
                state = plane_state[plane]
                state["tile_x"] = local_idx % tile_cols
                state["tile_y"] = global_idx // tile_cols
                state["chunk_first_row"] = local_idx < tile_cols
                state["quant_field_03"] = chunk.header.field_03
                state["quant_field_04"] = chunk.header.field_04
                if mode == 3:
                    state["mode_contexts"] = (
                        contexts.get(global_idx) if contexts is not None else None
                    )
                    # One map, four bands: plane 0 writes 0/1/2, plane 1 writes 3.
                    state.setdefault("mode_map", intra_modes)
                note, residual, raw = consume_known_mode_payload(
                    br, mode, plane, mode5_blocks, global_idx,
                    strict=strict, state=state,
                )
                after = chunk.offset * 8 + br.bit_pos
            except Exception as exc:  # noqa: BLE001 - diagnostic script
                where = (
                    f"chunk {chunk.index} plane {plane} tile {global_idx} "
                    f"(x={local_idx % tile_cols}, y={global_idx // tile_cols}) "
                    f"at byte {chunk.offset + br.byte_pos_floor}"
                )
                return chunk.offset + br.byte_pos_ceil, f"{where}: {type(exc).__name__}: {exc}"
            events.append(
                TileEvent(global_idx, plane, mode, before, after, note, residual, raw)
            )
        # FUN_001c0124:84-87 -- at the end of each plane pass the native reader
        # does `ptr -= count>>3; bits = 0; count = 0`, i.e. it drops the partial
        # bits and resumes on the next byte boundary.
        br.align_to_next_byte()

    return chunk.offset + br.byte_pos_ceil, None


def probe(
    name: str,
    data: bytes,
    max_tiles: int,
    show_events: int,
    mode_map: Path | None,
    mode5_y_map: Path | None,
    stateful_preview: Path | None,
    trace_csv: Path | None,
    planes: int | None,
    strict: bool,
    contexts: dict[int, object] | None = None,
) -> bool:
    """Walk one `.spi` member. Returns True only if every chunk landed exactly."""
    header, payload = split_spi(data)
    image_header = parse_image_header(data[4:])
    tile_cols = (image_header.width + 15) // 16
    tile_rows = (image_header.height + 15) // 16

    native_planes, fmt_info = plane_count_for(image_header.color_index)
    if planes is None:
        planes = native_planes
    fmt_note = (
        f"fmt={fmt_info['format']} planes={fmt_info['plane_count']} "
        f"components={fmt_info['components']}"
        if fmt_info
        else "fmt=? (libSPenBase.so not readable, assuming 1 plane)"
    )

    print(f"\n{name}")
    print(
        f"  image {image_header.width}x{image_header.height} "
        f"tiles={tile_cols}x{tile_rows} color_index={image_header.color_index} "
        f"{fmt_note} tile_rows_hint={image_header.tile_rows_hint} "
        f"flags={image_header.flags}"
    )
    print(f"  wrapper header={len(header)} payload={len(payload)}")
    print(f"  walking {planes} plane pass(es) per chunk, mode={'STRICT' if strict else 'GUESS'}")

    chunks = find_tile_chunks(payload, tile_rows, image_header.tile_rows_hint)

    # A chunk owns the bytes up to the next chunk's AA02, and the last one runs
    # to the end of the payload. These are hard, ground-truth-free constraints:
    # a correct decoder consumes each span exactly.
    bounds = [c.offset for c in chunks[1:]] + [len(payload)]

    print("  AA02 chunks:")
    for chunk, end in zip(chunks, bounds):
        print(
            f"    [{chunk.index}] offset={chunk.offset:<6} rows={chunk.rows} "
            f"tiles={tile_cols * chunk.rows}x{planes}planes  span={end - chunk.offset}B"
        )

    events: list[TileEvent] = []
    mode5_blocks: list = []
    plane_state: list[dict] = [{} for _ in range(planes)]
    intra_modes = ModeMap(tile_cols, tile_rows)
    results = []
    for chunk, expected_end in zip(chunks, bounds):
        end, stop = walk_chunk(
            chunk,
            payload,
            tile_cols,
            image_header.tile_rows_hint,
            planes,
            max_tiles,
            strict,
            events,
            mode5_blocks,
            contexts,
            plane_state,
            intra_modes,
        )
        results.append((chunk, expected_end, end, stop))
        if stop is not None:
            break

    print("  chunk verdicts:")
    exact = 0
    for chunk, expected_end, end, stop in results:
        if stop is not None:
            print(f"    [{chunk.index}] STOP  {stop}")
            continue
        delta = end - expected_end
        if delta == 0:
            exact += 1
            print(f"    [{chunk.index}] EXACT ended at {end} as expected")
        else:
            direction = "OVERRUN by" if delta > 0 else "UNDERRUN by"
            print(
                f"    [{chunk.index}] FAIL  consumed to {end}, expected {expected_end} "
                f"-> {direction} {abs(delta)}B"
            )

    modes = [event.mode for event in events]
    if modes:
        print(f"  tiles walked: {len(events)} (of {tile_cols * tile_rows * planes} geometric)")
        print(f"  mode counts: {dict(collections.Counter(modes))}")
    plane0_modes = [event.mode for event in events if event.plane == 0]
    for event in events[:show_events]:
        print(f"    plane={event.plane} tile {event.idx:03d}: mode={event.mode} payload_bits={event.start_bit}->{event.end_bit} {event.note}")
    if show_events > 0 and len(events) > show_events:
        print("    ...")
        tail_count = min(show_events, len(events) - show_events)
        for event in events[-tail_count:]:
            print(f"    plane={event.plane} tile {event.idx:03d}: mode={event.mode} payload_bits={event.start_bit}->{event.end_bit} {event.note}")

    ok = exact == len(chunks)
    print(
        f"  VERDICT: {'PASS' if ok else 'FAIL'} - {exact}/{len(chunks)} "
        "chunk boundaries hit exactly"
    )
    if mode_map is not None:
        write_mode_map(mode_map, plane0_modes, tile_cols, tile_rows)
        print(f"  wrote mode map: {mode_map}")
    if mode5_y_map is not None:
        write_mode5_y_map(mode5_y_map, mode5_blocks, tile_cols, tile_rows)
        print(f"  wrote mode5 Y map: {mode5_y_map}")
    if stateful_preview is not None:
        write_stateful_preview(stateful_preview, events, image_header.width, image_header.height, tile_cols, tile_rows)
        print(f"  wrote stateful preview: {stateful_preview}")
    if trace_csv is not None:
        with trace_csv.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "tile_idx",
                    "x_tile",
                    "y_tile",
                    "plane",
                    "mode",
                    "payload_start_bit",
                    "payload_end_bit",
                    "payload_bits",
                    "note",
                    "residual_dx",
                    "residual_dy",
                    "has_raw_planes",
                ]
            )
            for event in events:
                dx, dy = event.residual or ("", "")
                writer.writerow(
                    [
                        event.idx,
                        event.idx % tile_cols,
                        event.idx // tile_cols,
                        event.plane,
                        event.mode,
                        event.start_bit,
                        event.end_bit,
                        event.end_bit - event.start_bit,
                        event.note,
                        dx,
                        dy,
                        event.raw_planes is not None,
                    ]
                )
        print(f"  wrote trace CSV: {trace_csv}")

    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-tiles", type=int, default=1 << 30)
    parser.add_argument("--only", help="substring filter for member names")
    parser.add_argument("--show-events", type=int, default=12)
    parser.add_argument("--mode-map", type=Path, help="write a diagnostic tile-mode PNG")
    parser.add_argument("--mode5-y-map", type=Path, help="write raw mode-5 plane-0 blocks as grayscale PNG")
    parser.add_argument("--stateful-preview", type=Path, help="write a rough stateful reconstruction preview")
    parser.add_argument("--trace-csv", type=Path, help="write per-tile mode/bit-offset trace CSV")
    parser.add_argument(
        "--planes",
        type=int,
        default=None,
        help="override the plane-pass count (default: derived from color_index)",
    )
    parser.add_argument(
        "--guess",
        action="store_true",
        help="model unported handlers with placeholder bit counts instead of "
        "stopping; the resulting trace is NOT trustworthy",
    )
    parser.add_argument(
        "--context-csv",
        type=Path,
        metavar="NATIVE_D4000.CSV",
        help="FUN_001d4000 neighbour-context trace from spi_emu.py "
        "--context-trace; required to verify plane 1 mode 3",
    )
    parser.add_argument(
        "--verify-handlers",
        type=Path,
        metavar="NATIVE_TRACE.CSV",
        help="check each ported handler's bit count against a native trace "
        "produced by spi_emu.py --trace-csv, instead of walking the stream",
    )
    args = parser.parse_args()

    all_ok = True
    for name, data in iter_member_bytes(args.path):
        if args.only and args.only not in name:
            continue
        if args.verify_handlers:
            all_ok &= verify_handlers(
                name, data, args.verify_handlers, args.show_events, args.context_csv
            )
            continue
        all_ok &= probe(
            name,
            data,
            args.max_tiles,
            args.show_events,
            args.mode_map,
            args.mode5_y_map,
            args.stateful_preview,
            args.trace_csv,
            args.planes,
            strict=not args.guess,
            contexts=(
                load_mode_contexts(args.context_csv) if args.context_csv else None
            ),
        )
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
