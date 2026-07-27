#!/usr/bin/env python3
"""Reconstruct `.spi` / Maetel pixels from the bit-exact parse.

`pysdocx.spi.parse` reproduces the native bit consumption for all 3168 tiles, but
throws the decoded values away. This turns that parse into an actual decoder.

The native architecture, read off FUN_001c1c00 / FUN_001c1984, is simple:

    parse handler       fills four 16x16 component blocks (R, G, B, A)
    reconstruct handler blits them into the frame planes at the tile position,
                        or -- modes 0 and 1 -- copies a 16x16 region the frame
                        already holds, offset by a motion vector
    row post-pass       filters and rolls the line buffers

Usage -- decode and write a PNG (this is also what `pysdocx spi` wraps):

    .venv/bin/python -m pysdocx.spi.decode <file.sdocx|file.spi> \
        [--only 84bbec22] [--png out.png] [--compare reference.png]

The remaining flags (`--context-csv`, `--verify-blocks`) diff this decoder
against captures of the *native* one, block by block -- that separates "was the
block reconstructed right" from "was it placed right", which a whole-image diff
cannot. They need the reverse-engineering material, which is deliberately not in
the repo; without it the decoder is complete on its own.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from pysdocx.spi.parse import (
    BitReader,
    coefficient_tables,
    ModeMap,
    PaletteState,
    mode0_motion,
    consume_mode4_palette,
    find_tile_chunks,
    iter_member_bytes,
    load_mode_contexts,
    parse_image_header,
    parse_tile_header,
    plane_count_for,
    read_tile_mode,
    split_spi,
)

TILE = 16
BLOCK_PIXELS = TILE * TILE
COMPONENTS = 4  # R, G, B on plane 0; A on plane 1


class Blocks:
    """The four 16x16 component blocks a tile hands to the blit stage."""

    def __init__(self) -> None:
        self.data = [bytearray(BLOCK_PIXELS) for _ in range(COMPONENTS)]

    def fill(self, component: int, value: int) -> None:
        self.data[component] = bytearray([value]) * BLOCK_PIXELS

    def as_bytes(self) -> bytes:
        return b"".join(bytes(b) for b in self.data)


def reconstruct_mode4(blocks: Blocks, state: PaletteState) -> None:
    """Palette expansion -- plane 0 mode 4.

    FUN_001cf238's tail walks the 256 pixel indices and writes the three bytes
    of the chosen palette entry into the three component blocks. A flat tile
    skips the indices and fills all three from entry 0.
    """
    palette = state.palette
    if state.indices is None:
        for component in range(3):
            blocks.fill(component, palette[component])
        return
    for pixel, index in enumerate(state.indices[:BLOCK_PIXELS]):
        base = index * 3
        for component in range(3):
            blocks.data[component][pixel] = palette[base + component]


# Intra prediction tables, lifted out of the binary -- see SPI-HANDOFF.md 7.2.
STEP = [0, 5, 13, 21, 32]          # PTR_DAT_00204ab8 -> 0x3075c
INV = [0, 1638, 630, 390, 256]     # PTR_DAT_00204ac0 -> 0x30762, identica a HEVC
SIZE_CLASS = {4: 2, 8: 3, 16: 4}
FILT = {4: (3, 5, 4, 3), 8: (1, 3, 2, 2), 16: (1, 7, 4, 3)}
CORNER = {4: (3, 3, 2, 4, 3), 8: (1, 1, 2, 2, 2), 16: (1, 1, 6, 4, 3)}
ANGLE = [5, 13, 0, 1, 3, 7, 9, 11, 15, 17, 2, 4, 6, 8, 10, 12, 14, 0]
QUAD = [0, 8, 128, 136]            # quadrant offsets inside the 16x16 block
INNER = [0, 4, 64, 68]             # 4x4 offsets inside a quadrant

# --------------------------------------------------------------------- mode 2
# tile[0x0a] (the submode) picks the branch in FUN_001cf238: submode 0 goes to
# the NEON path, submode 2 -- the only one in the corpus -- to this scalar loop.
# Step and range come from tile[0x10cd]/[0x10ce]; the table at ctx[0x498] is a
# plain saturation to [0,255]. 27/27 against native_blocks.bin.
M2_STEP = 4
M2_RANGE = 65 * M2_STEP


def zigzag_signed(symbol: int) -> int:
    """Zigzag -> signed, as arithmetic (not the byte form `zigzag_byte` uses)."""
    return (-(symbol & 1) ^ symbol) >> 1


def reconstruct_mode2(symbols, above):
    """Vertical DPCM with a step of 4 -- plane 0 mode 2.

    `above` is the 16-pixel row that precedes the tile (see `tile_context`); rows
    1..15 predict from the row above inside the tile.
    """
    out = [0] * BLOCK_PIXELS
    for i in range(BLOCK_PIXELS):
        previous = out[i - TILE] if i >= TILE else above[i]
        value = previous + zigzag_signed(symbols[i]) * M2_STEP
        # The native wrap, then the saturating table at ctx[0x498].
        high = 0 if value <= (M2_STEP >> 1) + 0xFF else M2_RANGE
        wrapped = -high if -(M2_STEP >> 1) <= value else M2_RANGE
        out[i] = max(0, min(255, wrapped + value))
    return out

# --------------------------------------------------------------------- mode 3
# HEVC intra prediction (angular + filtered DC + planar) and the inverse
# transform, both 2199/2199 against spi_emu.py --intra-trace.
def predict(a, b, d, mode, clip=None):
    """`a` = left, `b` = top (33 samples each, index 0 is that array's corner).

    The same three families serve both planes; only the sample width differs.
    Plane 1 (alpha) is 8-bit, so the native stores wrap at 0xFF; plane 0 keeps
    int16 samples, and there the stores are `str h`, i.e. a truncation to short.
    Callers pass `clip` accordingly:

        plane 1   FUN_001c7540 / FUN_001c7b0c        default, & 0xFF
        plane 0   FUN_001c8708 / FUN_001c8b5c        s16
    """
    if clip is None:
        clip = lambda v: v & 0xFF  # noqa: E731
    if mode==17:
        return [clip(( d + (d-1-c)*a[1+r] + b[d]*(c+1) + (d-1-r)*b[1+c] + a[d]*(r+1) )//(2*d))
                for r in range(d) for c in range(d)]
    angle=ANGLE[mode]
    if angle==0:
        sc=SIZE_CLASS[d]; dc=clip((sum(a[1:d+1])+sum(b[1:d+1])+d)>>(sc+1))
        out=[[dc]*d for _ in range(d)]
        # The edge filter is inline here but a separate call natively
        # (FUN_001c80f8 on the alpha, FUN_001cb984 on plane 0), guarded by
        # `mode == 2`. Mode 2 is the only mode with angle 0 that reaches this
        # branch -- 17 leaves above -- so the two shapes agree.
        wt,wl,wd,rnd,sh=CORNER[d]; out[0][0]=clip((wt*b[1]+wl*a[1]+wd*dc+rnd)>>sh)
        wr,wdd,r2,s2=FILT[d]
        for c in range(1,d): out[0][c]=clip((wr*b[c+1]+wdd*dc+r2)>>s2)
        for r in range(1,d): out[r][0]=clip((wr*a[r+1]+wdd*dc+r2)>>s2)
        return [v for row in out for v in row]
    horiz=angle>=10; pure=13 if horiz else 5
    k=abs(angle-pure); step=STEP[k]; neg=angle<pure
    main,other=(a,b) if horiz else (b,a)
    ref={i:main[i] for i in range(min(len(main),2*d+2))}
    if neg and step:
        inv=INV[k]
        for x in range(-1,-((d*step)>>5)-3,-1):
            j=((-x)*inv+128)>>8
            if j<len(other): ref[x]=other[j]
    out=[0]*(d*d)
    for r in range(d):
        for c in range(d):
            rr,cc=(c,r) if horiz else (r,c)
            pos=-(rr+1)*step if neg else (rr+1)*step
            idx,frac=pos>>5,pos&31; i=cc+idx+1
            out[r*d+c]=clip(ref[i] if frac==0 else ((32-frac)*ref[i]+frac*ref[i+1]+16)>>5)
    return out

def inv_transform(co, d, mode):
    m=[list(co[r*d:(r+1)*d]) for r in range(d)]
    if mode==0:
        for r in range(1,d):
            for c in range(d): m[r][c]+=m[r-1][c]
    elif mode==1:
        for r in range(d):
            for c in range(1,d): m[r][c]+=m[r][c-1]
    return [v for row in m for v in row]


# Whether the [1,2,1] filter runs is a plain table lookup, not a threshold:
# both FUN_001d5abc (alpha) and FUN_001d5f44 (plane 0) index
# `UNK_00131ace[size_class * 0x11 + mode]`. An earlier round could only measure
# the corpus and inferred mid-point thresholds, leaving distance 3 at size 4 and
# distance 1 at size 8 declared Unknown; reading the table settles those and adds
# the size-16 row, which the alpha never exercises.
#
#   riga 2 (dim 4):  modi 3, 6, 9      riga 3 (dim 8):  modi 3..9
#   riga 4 (dim 16): modi 3..16
#
# Riga 1 si sovrappone in memoria alla tabella degli angoli: non usarla.
_INTRA_TABLES = None


def intra_tables() -> dict:
    global _INTRA_TABLES
    if _INTRA_TABLES is None:
        from pysdocx.spi import tables

        _INTRA_TABLES = tables.load_intra_tables()
    return _INTRA_TABLES


_DEQUANT_TABLES = None


def dequant_tables() -> dict:
    global _DEQUANT_TABLES
    if _DEQUANT_TABLES is None:
        from pysdocx.spi import tables

        _DEQUANT_TABLES = tables.load_dequant_tables()
    return _DEQUANT_TABLES


def smoothing_applies(d: int, mode: int) -> bool:
    if mode == 17:  # planar never reaches the lookup: it branches out first
        return False
    return bool(intra_tables()["filter_flags"][SIZE_CLASS[d]][mode])


def smooth_references(left, top, d):
    """FUN_001d5abc's [1,2,1]/4 pass.

    Both arrays collapse onto one shared corner; the last sample of each is left
    untouched, as in HEVC.

    The shared corner is built from **left[0]**, not top[0] -- FUN_001d5abc line
    163: `(left[1] + 2*left[0] + top[1] + 2) >> 2`, the same formula
    FUN_001d5f44 uses on the colour planes. The two only differ when the two
    corners differ, which is exactly the first tile row of an AA02 chunk
    (left[0] = 0x80 while top[0] replicates left[1]); everywhere else both
    corners are the same diagonal sample, which is why 300+ tiles could not tell
    them apart.
    """
    corner = (left[1] + 2 * left[0] + top[1] + 2) >> 2
    def run(a):
        return [corner] + [(a[k - 1] + 2 * a[k] + a[k + 1] + 2) >> 2 for k in range(1, 2 * d)] + [a[2 * d]]
    return run(left), run(top)


def mode2_context(plane_bytes, width, px, py, top_available):
    """The 16 pixels above a mode 2 tile, with the same substitution as mode 3."""
    if top_available:
        return [plane_bytes[(py - 1) * width + px + k] for k in range(TILE)]
    if px > 0:
        return [plane_bytes[py * width + px - 1]] * TILE
    return [0x80] * TILE


def tile_context(plane_bytes, width, px, py, top_available):
    """The 33 bytes above (x from -1 to +31) and the 33 to the left (corner first).

    The row above does not exist on the first tile row of an AA02 chunk. The
    substitution is symmetric: the missing side replicates the other side's first
    sample, and 0x80 stands in when both are missing. The two corners are
    independent -- the left array's is the true diagonal only when both
    neighbours exist.

    The left array holds 16 real samples; entries 17..32 replicate the last one,
    which is what `FUN_001d6efc` writes into `tile+0x2658`/`0x2660` and what a
    16x16 sub-block reads.
    """
    left_available = px > 0
    above = leftcol = None
    if top_available:
        above = [plane_bytes[(py - 1) * width + min(max(px - 1 + k, 0), width - 1)] for k in range(33)]
    if left_available:
        corner = plane_bytes[(py - 1) * width + px - 1] if top_available else 0x80
        leftcol = [corner] + [plane_bytes[(py + k) * width + px - 1] for k in range(TILE)]
        leftcol += [leftcol[TILE]] * (33 - len(leftcol))
    if not top_available and not left_available:
        return [0x80] * 33, [0x80] * 33
    if not top_available:
        return [leftcol[1]] * 33, leftcol
    if not left_available:
        return above, [above[0]] * 33
    return above, leftcol


def reconstruct_mode3(block, coded_blocks, above, leftcol, tables, tap=None):
    """Intra reconstruction of one alpha tile -- plane 1 mode 3.

    Sub-blocks are decoded in bitstream order and each one predicts from what the
    earlier ones already wrote, so this has to run inside the tile loop.

    The reference arrays are **not** HEVC's generic substitution process: they are
    switches by sub-block position -- `FUN_001cbf98` (4x4, index `sub*4 + i`) and
    `FUN_001cc150` (8x8, index `sub`) -- transcribed case by case. Both are
    identical to their plane 0 twins `FUN_001cc318` / `FUN_001cc4dc`, so
    `subblock_refs_dim4` / `subblock_refs_dim8` serve both planes; only the
    sample type differs (bytes here, int16 there).

    What no generic model reproduces: the arrays are locals of `FUN_001d5abc`
    (`local_a0` = left, `local_d0` = top), zeroed **only on entry** and reused
    for the whole sub-block loop, so entries a case does not write stay stale
    from the previous sub-block. Case 3 (the 4x4 at (4,4)) writes only
    `top[0..4]` and the angular modes read the stale `top[5..8]` for real.
    """
    for coded in coded_blocks:
        d, size_class = coded["block_dim"], coded["size_class"]
        by_index = {sub["index"]: sub for sub in coded["subblocks"]}
        # Una chiamata di FUN_001d5abc per blocco codificato: gli array vivono
        # qui, azzerati una volta sola, e le voci non scritte restano stantie.
        n_refs = 2 * d + 1
        left_out = [0] * n_refs
        top_out = [0] * n_refs
        for position, mode in enumerate(coded["modes"]):
            # An unsplit 16x16 covers the whole tile; an 8x8 is one quadrant; a
            # 4x4 is one cell inside a quadrant.
            if d == TILE:
                offset = 0
            else:
                offset = QUAD[coded["sub"]] + (INNER[position] if d == 4 else 0)
            bx, by = offset % TILE, offset // TILE
            if d == TILE:
                # FUN_001d5abc righe 429-438: i due array del tile, per intero.
                top_out[:] = above[:n_refs]
                left_out[:] = leftcol[:n_refs]
            elif d == 8:
                subblock_refs_dim8(leftcol, above, block, bx, by, coded["sub"],
                                   left_out, top_out)
            else:
                subblock_refs_dim4(leftcol, above, block, bx, by,
                                   coded["sub"] * 4 + position, left_out, top_out)
            left, top = list(left_out), list(top_out)
            if smoothing_applies(d, mode):
                left, top = smooth_references(left, top, d)
            pred = predict(left, top, d, mode)
            values = pred
            if position in by_index:
                scan = tables["scans"][(size_class, by_index[position]["context"])]
                coefficients = [0] * (d * d)
                for at, level in by_index[position]["coeffs"]:
                    if at >= len(scan):
                        continue  # see the overshoot note in parse.py
                    coefficients[scan[at]] = level
                residual = inv_transform(coefficients, d, mode)
                values = [max(0, min(255, pred[k] + residual[k])) for k in range(d * d)]
            if tap is not None:
                tap({"sub": coded["sub"], "seq": position, "dim": d, "mode": mode,
                     "left": list(left), "top": list(top), "pred": list(pred),
                     "out": list(values)})
            for row in range(d):
                for col in range(d):
                    block[(by + row) * TILE + bx + col] = values[row * d + col]



# --------------------------------------------- plane 0 mode 3: dequant + trasformate
# Le tre trasformate inverse che FUN_001d31b8 chiama attraverso i puntatori del
# contesto. Trascritte dalla C decompilata, non dedotte: il contenuto informativo
# e' *dove cade ogni troncamento a 16 bit*, e nessun fitting parametrico lo
# indovina (si fermava a 52/60 vettori casuali).
#
#   4x4 e 8x8   butterfly a lifting stile H.264, ogni intermedio troncato a short
#   16x16       DCT-16 intera di HEVC, matrice standard, shift 7 poi 12
#
# Verificate con apk-re/scripts/spi_probe_native.py, che chiama la funzione
# nativa isolata sotto Unicorn: 4x4 300/300, 8x8 460/460 su vettori casuali e
# casi limite, e **61/61 sulle chiamate reali** di basic18_recon0.csv.
# Dettagli in apk-re/SPI-HANDOFF.md 7.3.


def s16(v):
    """Troncamento a short, come fa ogni assegnazione intermedia nella C."""
    return ((v + 0x8000) & 0xFFFF) - 0x8000


def lsr(v, n):
    """Shift logico su registro a 32 bit -- la C scrive (uint)(int)x >> n."""
    return (v & 0xFFFFFFFF) >> n


def itransform4(b):
    """`b` sono 16 short, modificati in place. `dc_only` = param_2 == 1."""
    v9 = b[0]
    v34 = s16(b[4] + (b[12] >> 1))
    v38 = s16(b[12] - (b[4] >> 1))
    v30 = s16(b[8] + v9)
    v9 = s16(v9 - b[8])
    v25 = s16(v34 + v30)
    v28 = s16(v9 - v38)
    v38 = s16(v38 + v9)
    v30 = s16(v30 - v34)
    v31 = s16(b[5] + (b[13] >> 1))
    v32 = s16(b[7] + (b[15] >> 1))
    v9 = s16(b[9] + b[1])
    v34 = s16(b[11] + b[3])
    v13 = s16(v31 + v9)
    v35 = s16(b[6] + (b[14] >> 1))
    v14 = s16(v32 + v34)
    v37 = s16(b[14] - (b[6] >> 1))
    v33 = s16(b[15] - (b[7] >> 1))
    v29 = s16(b[10] + b[2])
    v36 = s16(b[13] - (b[5] >> 1))
    v10 = s16(b[2] - b[10])
    v11 = s16(b[3] - b[11])
    v26 = s16(v35 + v29)
    v15 = s16(v11 - v33)
    v12 = s16(b[1] - b[9])
    v16 = s16(v12 - v36)
    v27 = s16(v10 - v37)
    i17 = s16(v14 - s16(lsr(v13, 1)))
    i18 = s16(v13 + s16(lsr(v14, 1)))
    i1 = s16(v25 - v26) + 0x20
    v33 = s16(v33 + v11)
    i19 = s16(v16 + s16(lsr(v15, 1)))
    i2 = s16(v27 + v28) + 0x20
    i3 = s16(v26 + v25) + 0x20
    b[8] = s16(lsr(i1 + i17, 6))
    v36 = s16(v36 + v12)
    v37 = s16(v37 + v10)
    i20 = s16(v15 - s16(lsr(v16, 1)))
    b[1] = s16(lsr(i2 + i19, 6))
    i4 = s16(v28 - v27) + 0x20
    i21 = s16(v36 + s16(lsr(v33, 1)))
    v34 = s16(v34 - v32)
    i5 = s16(v37 + v38) + 0x20
    v9 = s16(v9 - v31)
    b[9] = s16(lsr(i4 + i20, 6))
    v29 = s16(v29 - v35)
    i22 = s16(v33 - s16(lsr(v36, 1)))
    b[2] = s16(lsr(i5 + i21, 6))
    i6 = s16(v38 - v37) + 0x20
    i23 = s16(v9 + s16(lsr(v34, 1)))
    i7 = s16(v29 + v30) + 0x20
    i24 = s16(v34 - s16(lsr(v9, 1)))
    i8 = s16(v30 - v29) + 0x20
    b[10] = s16(lsr(i6 + i22, 6))
    b[4] = s16(lsr(i1 - i17, 6))
    b[12] = s16(lsr(i3 - i18, 6))
    b[5] = s16(lsr(i4 - i20, 6))
    b[14] = s16(lsr(i5 - i21, 6))
    b[11] = s16(lsr(i8 + i24, 6))
    acc = i3 + i18
    b[13] = s16(lsr(i2 - i19, 6))
    b[6] = s16(lsr(i6 - i22, 6))
    b[3] = s16(lsr(i7 + i23, 6))
    b[7] = s16(lsr(i8 - i24, 6))
    b[15] = s16(lsr(i7 - i23, 6))
    b[0] = s16(lsr(acc, 6))
    return b

def itransform4_dc(b):
    b[0] = s16(lsr(b[0] + 0x20, 6))
    return b


def itransform8(b):
    """64 short in place. Due passate: colonne in un buffer temporaneo, poi righe."""
    b[0] = s16(b[0] + 0x20)
    t = [0] * 64
    for x in range(8):
        c0, c1, c2, c3 = b[x], b[8 + x], b[16 + x], b[24 + x]
        c4, c5, c6, c7 = b[32 + x], b[40 + x], b[48 + x], b[56 + x]
        v19 = s16(c4 + c0)
        v18 = s16(c0 - c4)
        i1 = c5 + c3 + c1 + (c1 >> 1)
        v21 = s16(c6 - (c2 >> 1))
        v20 = s16(c2 + (c6 >> 1))
        i9 = c5 - (c3 + c7 + (c7 >> 1))
        i2 = (c7 - (c3 + (c3 >> 1))) + c1
        i10 = (c7 + c5 + (c5 >> 1)) - c1
        v5 = s16(s16(i1) - s16(i9 >> 2))
        v6 = s16(v20 + v19)
        v8 = s16(s16(i10) - s16(i2 >> 2))
        v7 = s16(v18 - v21)
        v17 = s16(s16(i2) + s16(i10 >> 2))
        v21 = s16(v21 + v18)
        t[x] = s16(v5 + v6)
        v18 = s16(s16(i9) + s16(i1 >> 2))
        t[8 + x] = s16(v7 - v8)
        v19 = s16(v19 - v20)
        t[40 + x] = s16(v21 - v17)
        t[16 + x] = s16(v17 + v21)
        t[48 + x] = s16(v8 + v7)
        t[24 + x] = s16(v18 + v19)
        t[32 + x] = s16(v19 - v18)
        t[56 + x] = s16(v6 - v5)

    for y in range(8):
        r = t[y * 8 : y * 8 + 8]
        r0, r1, r2, r3, r4, r5, r6, r7 = r
        i22 = r4 + r0
        i11 = r0 - r4
        i1 = r2 + (r6 >> 1)
        i10 = r6 - (r2 >> 1)
        i2 = r5 + r3 + r1 + (r1 >> 1)
        i12 = r5 - (r3 + r7 + (r7 >> 1))
        i9 = i1 + i22
        i13 = i11 - i10
        i3 = (r7 - (r3 + (r3 >> 1))) + r1
        i14 = (r7 + r5 + (r5 >> 1)) - r1
        i15 = i2 - (i12 >> 2)
        i10 = i10 + i11
        i11 = i14 - (i3 >> 2)      # i3 ancora il vecchio: l'ordine conta
        i3 = i3 + (i14 >> 2)
        i12 = i12 + (i2 >> 2)
        i22 = i22 - i1
        b[y] = s16(lsr(i15 + i9, 6))
        b[8 + y] = s16(lsr(i13 - i11, 6))
        b[40 + y] = s16(lsr(i10 - i3, 6))
        b[32 + y] = s16(lsr(i22 - i12, 6))
        b[16 + y] = s16(lsr(i3 + i10, 6))
        b[24 + y] = s16(lsr(i12 + i22, 6))
        b[48 + y] = s16(lsr(i11 + i13, 6))
        b[56 + y] = s16(lsr(i9 - i15, 6))
    return b

def itransform8_dc(b):
    b[0] = s16(lsr(b[0] + 0x20, 6))
    return b


# Misurata dalla sonda a impulsi, poi divisa per 2: e' la transMatrix a 16 punti
# di HEVC, identica riga per riga.
M16 = [
 [64,64,64,64,64,64,64,64,64,64,64,64,64,64,64,64],
 [90,87,80,70,57,43,25,9,-9,-25,-43,-57,-70,-80,-87,-90],
 [89,75,50,18,-18,-50,-75,-89,-89,-75,-50,-18,18,50,75,89],
 [87,57,9,-43,-80,-90,-70,-25,25,70,90,80,43,-9,-57,-87],
 [83,36,-36,-83,-83,-36,36,83,83,36,-36,-83,-83,-36,36,83],
 [80,9,-70,-87,-25,57,90,43,-43,-90,-57,25,87,70,-9,-80],
 [75,-18,-89,-50,50,89,18,-75,-75,18,89,50,-50,-89,-18,75],
 [70,-43,-87,9,90,25,-80,-57,57,80,-25,-90,-9,87,43,-70],
 [64,-64,-64,64,64,-64,-64,64,64,-64,-64,64,64,-64,-64,64],
 [57,-80,-25,90,-9,-87,43,70,-70,-43,87,9,-90,25,80,-57],
 [50,-89,18,75,-75,-18,89,-50,-50,89,-18,-75,75,18,-89,50],
 [43,-90,57,25,-87,70,9,-80,80,-9,-70,87,-25,-57,90,-43],
 [36,-83,83,-36,-36,83,-83,36,36,-83,83,-36,-36,83,-83,36],
 [25,-70,90,-80,43,9,-57,87,-87,57,-9,-43,80,-90,70,-25],
 [18,-50,75,-89,89,-75,50,-18,-18,50,-75,89,-89,75,-50,18],
 [9,-25,43,-57,70,-80,87,-90,90,-87,80,-70,57,-43,25,-9]]

def itransform16(vals, s1=7, s2=12, clip=True):
    d = 16
    c = [vals[r*d:(r+1)*d] for r in range(d)]
    t = [[0]*d for _ in range(d)]
    for col in range(d):
        for y in range(d):
            acc = sum(c[k][col] * M16[k][y] for k in range(d))
            v = (acc + (1 << (s1-1))) >> s1 if s1 else acc
            t[y][col] = max(-32768, min(32767, v)) if clip else v
    out = [0]*(d*d)
    for y in range(d):
        for x in range(d):
            acc = sum(t[y][k] * M16[k][x] for k in range(d))
            out[y*d+x] = s16((acc + (1 << (s2-1))) >> s2 if s2 else acc)
    return out


# ------------------------------------------- plane 0 mode 3: predizione e colore
# FUN_001d5f44 e' l'analogo di FUN_001d5abc sul plane 0, e la catena e' la stessa
# in int16. Dal sito di chiamata in FUN_001d0044:
#
#   per banda 0..2:  1 bit -> split;  per sub:
#       FUN_001d2874(tile, sub, band)   coefficienti, sempre a tile+0x140
#       FUN_001d31b8(tile, 0, 0)        dequant + trasformata inversa, in place
#       FUN_001d5f44(ctx, tile, sub, band)  predizione + somma + collocazione
#
# I due `0` in FUN_001d31b8 sono letterali: il `band*0x200 + sub*0x80` che il
# documento riportava vale per altri siti di chiamata. Il buffer dei coefficienti
# tiene esattamente l'unita' corrente -- un 16x16, un 8x8, oppure quattro 4x4 a
# passo 0x20.
#
# Le tre bande non sono R/G/B ma **YCoCg-R**, con la croma sbiasata di +0x100:
# a croma nulla la conversione rende R=G=B, che e' il grigio piatto che il nativo
# emette. Verificato 129/129 chiamate su basic-18 e 27/27 su page-59.


def place_residual(pred, coeff, flag, d, bitdepth):
    """`FUN_001c6ea4` (ctx+0x620): somma del residuo e clamp.

    Tre rami, non due come sull'alpha:

        flag == 1   solo il DC: `coeff[0]` sommato a tutta la predizione
        flag == 7   residuo pieno
        altro       copia della predizione, senza clamp

    La somma e' **troncata a short prima** del clamp, non dopo. Il nono parametro
    (la profondita' di bit) viaggia sullo stack, non in un registro: con otto
    interi gia' in x0-x7 l'AAPCS lo mette a `[sp]`, e Ghidra lo perde -- il sito
    di chiamata sembra avere otto argomenti.
    """
    hi = (1 << bitdepth) - 1
    if flag == 1:
        return [max(0, min(hi, s16(p + coeff[0]))) for p in pred]
    if flag == 7:
        return [max(0, min(hi, s16(pred[k] + coeff[k]))) for k in range(d * d)]
    return list(pred)


def smooth_references_plane0(left, top, d):
    """Il [1,2,1]/4 di FUN_001d5f44.

    Identico a `smooth_references` dell'alpha a meno del clamp a int16: il corner
    comune si costruisce da `left[0]`, non da `top[0]`, in tutti e due i piani.
    """
    corner = s16((left[1] + 2 * left[0] + top[1] + 2) >> 2)

    def run(a):
        return ([corner]
                + [s16((a[k - 1] + 2 * a[k] + a[k + 1] + 2) >> 2) for k in range(1, 2 * d)]
                + [a[2 * d]])
    return run(left), run(top)


def color_inverse(band0, band1, band2):
    """Le tre bande del plane 0 -> RGB, il loop di FUN_001c1d3c.

    E' un lifting reversibile in stile YCoCg-R, ma i ruoli dei canali non sono
    quelli del nome: si trascrivono dalla C invece di dedurli.

        cg = band1 - 0x100
        t  = band0 - (cg >> 1)
        R  = clamp(t + cg)
        G  = clamp(t - ((band2 - 0x100) >> 1))
        B  = clamp((band2 - 0x100) + G)          <- il G **gia' clampato**

    A croma nulla (band1 = band2 = 0x100) restano R = G = B = band0: e' il grigio
    piatto che il nativo emette, e la ragione per cui la conversione doveva
    esserci.

    Il nativo scrive `(band2 + 0x1ff00) >> 1` invece di `(band2 - 0x100) >> 1`:
    `0x1ff00 = -0x100 + 0x20000`, e il `0x10000` che sopravvive allo shift
    sparisce nel troncamento a short. Stesso valore, per costruzione.
    """
    cg = band1 - 0x100
    co = band2 - 0x100
    t = band0 - (cg >> 1)
    r = max(0, min(255, s16(t + cg)))
    g = max(0, min(255, s16(t - (co >> 1))))
    b = max(0, min(255, s16(co + g)))
    return r, g, b


def color_forward(r, g, b):
    """RGB -> le tre bande, l'inversa esatta di `color_inverse`.

    Serve perche' i riferimenti fra tile (`tile+0x3120` / `+0x31e6`) non sono
    tenuti in piani separati: FUN_001d6478 costruisce il contesto in **8 bit**
    dal frame RGB gia' scritto, e FUN_001ce290 lo riconverte in int16. Il lifting
    e' reversibile, quindi le due strade coincidono.
    """
    co = b - g
    t = g + (co >> 1)
    cg = r - t
    return t + (cg >> 1), cg + 0x100, co + 0x100


def dequant(coeffs, d, quant, group, flag, tables):
    """`FUN_001c5e78` / `FUN_001c6170` / `FUN_001c6468`, i tre dequantizzatori.

    `tile[0x3a]` (23 su tutte le bande colore del corpus) indicizza una tabella
    il cui nibble alto e' l'indice di matrice e quello basso lo shift;
    `tile[0x31] == 2` sceglie il gruppo di matrici. `flag == 1` significa **solo
    il DC**: gli altri coefficienti restano intatti.
    """
    entry = tables["shift_matrix"][quant]
    matrix_index, shift = entry >> 4, entry & 0xF
    out = list(coeffs)
    n = d * d if flag != 1 else 1
    if d == 16:
        scale = tables["scale16"][matrix_index]
        for i in range(n):
            out[i] = s16((((coeffs[i] * scale) << shift) + 4) >> 3)
        return out
    matrix = (tables["matrix4"] if d == 4 else tables["matrix8"])[group][matrix_index]
    base = 4 if d == 4 else 6
    for i in range(n):
        product = coeffs[i] * matrix[i]
        if shift >= base:
            out[i] = s16(product << (shift - base))
        else:
            out[i] = s16((product + (1 << (base - shift - 1))) >> (base - shift))
    return out


# The clamp width of FUN_001c6ea4, per band, read out of the native at the call
# site (`spi_emu.py --predict0-trace` prints it): luma 8, chroma 9. The extra bit
# is what a reversible lifting needs -- chroma is biased by +0x100 and legitimately
# exceeds 255, and clamping it at 255 corrupts whole tiles. Neither basic-18 nor
# page-59 saturates, so those two samples cannot tell 8 from 9; Allsamsungnotes
# page 7 does, which is why a third sample was worth generating.
PLANE0_BITDEPTH = (8, 9, 9)


# --------------------------------------- riferimenti dei sotto-blocchi (plane 0)
# `FUN_001cc318` (4x4) e `FUN_001cc4dc` (8x8) riempiono i due array di
# riferimento, e vanno trascritte alla lettera perche' **non sono una regola di
# sostituzione**. Il modello generico HEVC che serve l'alpha -- "un campione non
# ancora decodificato non e' disponibile, replica in avanti l'ultimo" -- qui e'
# sbagliato per due motivi:
#
#   * alcuni casi **non scrivono l'array intero**. Il caso 3 di FUN_001cc318 (il
#     4x4 in (4,4)) scrive solo `top[0..4]`; `top[5..8]` restano quelli del
#     sotto-blocco precedente, perche' gli array sono locali di FUN_001d5f44,
#     azzerati **solo all'ingresso** e riusati per tutto il loop. Col modo 5
#     (angolo 7, passo 13) il predittore li legge davvero;
#   * altri casi leggono dal piano posizioni che il modello generico
#     considererebbe non disponibili, prendendo quindi lo zero del buffer invece
#     di una replica.
#
# Gli offset in byte della C si leggono cosi', col piano a 16 short per riga:
#   dst - 0x22 = (col-1, row-1)   dst - 2    = (col-1, row+0)
#   dst - 0x1a = (col+3, row-1)   dst + 0x1e = (col-1, row+1)
#   dst - 0x12 = (col+7, row-1)   dst + 0x3e = (col-1, row+2)  ... +0x20/riga


def _plane_at(plane, col, row):
    """Il piano 16x16 di int16 che FUN_001d5f44 sta riempiendo, letto grezzo.

    Fuori dal tile non esiste "non disponibile": il nativo indicizza e basta, e
    quel che trova e' quel che usa.
    """
    if 0 <= col < TILE and 0 <= row < TILE:
        return plane[row * TILE + col]
    return 0


def subblock_refs_dim4(left_tile, top_tile, plane, col, row, n, left_out, top_out):
    """`FUN_001cc318(left_tile, top_tile, dst, &left_out, &top_out, sub*4 + i)`.

    `n` = `sub * 4 + i`, cioe' la posizione del 4x4 fra i 16 del tile. Gli array
    hanno 9 voci (2*4+1); le voci che un caso non tocca restano quelle di prima.
    """
    def above(k):      # (col-1+k, row-1)
        return _plane_at(plane, col - 1 + k, row - 1)

    def left_col(k):   # (col-1, row+k)
        return _plane_at(plane, col - 1, row + k)

    def left_tail_4():
        # LAB_001cc430: quattro righe, poi la quarta replicata su [4..8].
        for k in range(3):
            left_out[1 + k] = left_col(k)
        last = left_col(3)
        for k in range(4, 9):
            left_out[k] = last

    def left_tail_8():
        # LAB_001cc3c4: tutte e otto le righe, l'ottava anche su [8].
        for k in range(7):
            left_out[1 + k] = left_col(k)
        left_out[8] = left_col(7)

    if n == 0:
        top_out[0:9] = top_tile[0:9]
        left_out[0:9] = left_tile[0:9]
        return
    if n in (1, 4, 5):
        # Finestra scorrevole sull'array del tile: colonna 4, 8, 12.
        off = {1: 4, 4: 8, 5: 12}[n]
        top_out[0:9] = top_tile[off:off + 9]
        left_out[0] = top_out[0]
        (left_tail_8 if n == 4 else left_tail_4)()
        return
    if n in (2, 8, 10):
        off = {2: 4, 8: 8, 10: 12}[n]
        left_out[0:9] = left_tile[off:off + 9]
        top_out[0] = left_out[0]
        for k in range(1, 9):
            top_out[k] = above(k)
        return
    if n == 3:
        # Solo [0..4]. La coda [5..8] resta stantia: e' il punto della funzione.
        for k in range(5):
            top_out[k] = above(k)
        left_out[0] = above(0)
        left_tail_4()
        return
    if n in (6, 9, 14):
        for k in range(9):
            top_out[k] = above(k)
        left_out[0] = above(0)
        left_tail_4()
        return
    if n == 12:
        for k in range(9):
            top_out[k] = above(k)
        left_out[0] = above(0)
        left_tail_8()
        return
    if n in (7, 11, 13, 15):
        for k in range(5):
            top_out[k] = above(k)
        for k in range(5, 9):
            top_out[k] = top_out[4]
        left_out[0] = above(0)
        left_tail_4()
        return
    raise NotImplementedError(f"FUN_001cc318: caso {n} non previsto")


def subblock_refs_dim8(left_tile, top_tile, plane, col, row, sub, left_out, top_out):
    """`FUN_001cc4dc(left_tile, top_tile, dst, &left_out, &top_out, sub)`.

    Quattro casi, array da 17 voci (2*8+1).
    """
    def above(k):
        return _plane_at(plane, col - 1 + k, row - 1)

    def left_col(k):
        return _plane_at(plane, col - 1, row + k)

    def left_tail():
        for k in range(7):
            left_out[1 + k] = left_col(k)
        last = left_col(7)
        for k in range(8, 17):
            left_out[k] = last

    if sub == 0:
        top_out[0:17] = top_tile[0:17]
        left_out[0:17] = left_tile[0:17]
        return
    if sub == 1:
        top_out[0:17] = top_tile[8:25]
        left_out[0] = top_out[0]
        left_tail()
        return
    if sub == 2:
        left_out[0:17] = left_tile[8:25]
        top_out[0] = left_out[0]
        for k in range(1, 17):
            top_out[k] = above(k)
        return
    if sub == 3:
        for k in range(9):
            top_out[k] = above(k)
        for k in range(9, 17):
            top_out[k] = top_out[8]
        left_out[0] = above(0)
        left_tail()
        return
    raise NotImplementedError(f"FUN_001cc4dc: caso {sub} non previsto")


def reconstruct_mode3_plane0(blocks, coded_blocks, contexts, tables, dequant_tables,
                             bitdepth=PLANE0_BITDEPTH):
    """Intra reconstruction of one colour tile -- plane 0 mode 3.

    `contexts` is `(tops, lefts)`, three 33-byte arrays each, built from the RGB
    frame with the same rule as the alpha's `tile_context`. They are converted to
    the decoder's three bands here, because that is what the native does: the
    context lives in 8-bit RGB (FUN_001d6478) and FUN_001ce290 lifts it into the
    int16 arrays at `tile+0x3120` / `+0x31e6`.

    Bands are independent: each keeps its own 16x16 int16 plane and its own
    sub-block ordering. The three planes go back to RGB at the end.
    """
    band_top, band_left = contexts

    planes = [[0] * BLOCK_PIXELS for _ in range(3)]
    done = [[False] * BLOCK_PIXELS for _ in range(3)]

    for coded in coded_blocks:
        band = coded["band"]
        if band > 2:
            continue
        d, size_class = coded["block_dim"], coded["size_class"]
        plane, seen = planes[band], done[band]
        top_ref = [v[band] for v in band_top]
        left_ref = [v[band] for v in band_left]
        by_index = {sub["index"]: sub for sub in coded["subblocks"]}

        # One `coded` entry is one FUN_001d5f44 call, and these two arrays are
        # that call's stack locals: zeroed on entry, then **reused** across the
        # sub-block loop. Entries a case does not write keep the previous
        # sub-block's value, which is exactly what the native reads back.
        top_out = [0] * (2 * d + 1)
        left_out = [0] * (2 * d + 1)

        for position, mode in enumerate(coded["modes"]):
            if d == TILE:
                offset = 0
            else:
                offset = QUAD[coded["sub"]] + (INNER[position] if d == 4 else 0)
            bx, by = offset % TILE, offset // TILE

            if d == TILE:
                # No switch for a whole-tile block: FUN_001d5f44 loads both
                # arrays straight out of tile+band*0x42+0x3120 / +0x31e6.
                top_out[:] = top_ref[: 2 * d + 1]
                left_out[:] = left_ref[: 2 * d + 1]
            elif d == 8:
                subblock_refs_dim8(left_ref, top_ref, plane, bx, by,
                                   coded["sub"], left_out, top_out)
            else:
                subblock_refs_dim4(left_ref, top_ref, plane, bx, by,
                                   coded["sub"] * 4 + position, left_out, top_out)

            top, left = list(top_out), list(left_out)
            if smoothing_applies(d, mode):
                left, top = smooth_references_plane0(left, top, d)
            values = predict(left, top, d, mode, clip=s16)

            # FUN_001d2874 sets the flag: 1 when the only coefficient is the DC,
            # 7 otherwise, 0 when the sub-block is absent from the mask.
            sub = by_index.get(position)
            if sub is None:
                flag, residual = 0, [0] * (d * d)
            else:
                # Positions stay inside the scan now that plane 0 goes through
                # the right coefficient decoder (FUN_001d42a8, picked by
                # `tile[0x38] != 0`): the overshoot to 638 on a 256-entry order
                # was an artefact of the alpha plane's escape formula, not
                # something the native does. Max position on basic-18 is 255.
                scan = tables["scans"][(size_class, sub["context"])]
                coefficients = [0] * (d * d)
                for at, level in sub["coeffs"]:
                    if at >= len(scan):
                        continue
                    coefficients[scan[at]] = level
                flag = 1 if len(sub["coeffs"]) == 1 and sub["coeffs"][0][0] == 0 else 7
                residual = dequant(coefficients, d, coded["quant"], coded["quant_group"],
                                   flag, dequant_tables)
                if d == 4:
                    itransform4_dc(residual) if flag == 1 else itransform4(residual)
                elif d == 8:
                    itransform8_dc(residual) if flag == 1 else itransform8(residual)
                else:
                    residual = itransform16(residual)
            values = place_residual(values, residual, flag, d, bitdepth[band])

            for row in range(d):
                for col in range(d):
                    plane[(by + row) * TILE + bx + col] = values[row * d + col]
                    seen[(by + row) * TILE + bx + col] = True

    for k in range(BLOCK_PIXELS):
        r, g, b = color_inverse(planes[0][k], planes[1][k], planes[2][k])
        blocks[0][k], blocks[1][k], blocks[2][k] = r, g, b


def plane0_tile_context(frame, px, py, top_available):
    """The two int16 reference arrays of a colour tile, 33 samples each.

    Natively these live at `tile+0x3120` (top) and `tile+0x31e6` (left), one
    `0x42`-byte slot per band, and they are built in two steps: `FUN_001d6478`
    lays out the neighbours in **8-bit RGB**, then `FUN_001ce290` lifts them into
    the bands. Reproduced here in the same order, because the lift is only
    reversible on unclamped values.

    The left column has 16 real samples; the rest replicate the last one, which
    is HEVC's substitution and what the native array holds.
    """
    tops, lefts = [], []
    for component in range(3):
        above, leftcol = tile_context(frame.planes[component], frame.width, px, py,
                                      top_available)
        tops.append(above)
        lefts.append(leftcol)  # tile_context replica gia' la coda [17..32]
    band_top = [color_forward(tops[0][k], tops[1][k], tops[2][k]) for k in range(33)]
    band_left = [color_forward(lefts[0][k], lefts[1][k], lefts[2][k]) for k in range(33)]
    return band_top, band_left


class Frame:
    """The decoded planes, padded out to whole tiles.

    Four 8-bit planes: R, G, B on plane pass 0, alpha on pass 1. Modes 0 and 1
    copy a 16x16 region that is already here, which is why reconstruction has to
    be a running frame and not a bag of independent blocks.
    """

    def __init__(self, tile_cols: int, tile_rows: int):
        self.width = tile_cols * TILE
        self.height = tile_rows * TILE
        self.planes = [bytearray(self.width * self.height) for _ in range(COMPONENTS)]

    def blit_block(self, component: int, x: int, y: int, block) -> None:
        for row in range(TILE):
            dst = (y + row) * self.width + x
            self.planes[component][dst : dst + TILE] = block[row * TILE : (row + 1) * TILE]

    def copy_region(self, component: int, sx: int, sy: int, x: int, y: int) -> None:
        """FUN_001c1984's motion copy: 16x16 from (sx, sy) to (x, y)."""
        if sx < 0 or sy < 0 or sx + TILE > self.width or sy + TILE > self.height:
            return
        plane = self.planes[component]
        for row in range(TILE):
            src = (sy + row) * self.width + sx
            dst = (y + row) * self.width + x
            plane[dst : dst + TILE] = plane[src : src + TILE]

    def to_rgba(self, width: int, height: int) -> bytes:
        """The frame planes are **G, R, B**, not R, G, B.

        The three planes are `ctx[0x3e0] + 0x20/0x28/0x30`, and every path writes
        them in that order: mode 4 blits its palette bytes, mode 2 its three
        symbol blocks, and mode 3's colour transform its three stores. Which
        channel each one *is* only becomes visible on coloured content, and the
        first three reference samples are entirely monochrome -- R == G == B on
        all 402688 + 3619200 + 3619200 pixels -- so they could not tell any
        permutation apart. Allsamsungnotes page 7 has 144661 pixels with R != G,
        and it pins the order: swapping the first two planes takes it from 4.0%
        differing to 205 pixels, while the other three stay at 0.
        """
        out = bytearray(width * height * 4)
        for row in range(height):
            base = row * self.width
            for col in range(width):
                o = (row * width + col) * 4
                out[o] = self.planes[1][base + col]
                out[o + 1] = self.planes[0][base + col]
                out[o + 2] = self.planes[2][base + col]
                out[o + 3] = self.planes[3][base + col]
        return bytes(out)


# Mode 0 has no coded vector: it copies the tile above when it is at the left
# edge, otherwise the tile to its left (FUN_001cd124, DAT_0012ed78/DAT_0012ee88).
MOTION_FROM_ABOVE = (0, TILE)
MOTION_FROM_LEFT = (TILE, 0)


def decode(
    data: bytes,
    contexts: dict[int, object] | None = None,
    above_by_tile: dict[tuple[int, int], bytes] | None = None,
    motion_by_tile: dict[tuple[int, int], tuple[int, int]] | None = None,
    context_tap=None,
    subblock_tap=None,
) -> tuple[dict[tuple[int, int], bytes], dict, Frame]:
    """Walk every tile, reconstructing the blocks each one produces.

    Returns {(plane, tile_index): 4x256 block bytes} plus the image header
    fields, so a caller can check blocks before any frame assembly exists.

    `context_tap(tile_index, above, leftcol)` is called for every alpha mode 3
    tile with the reference context this decoder built, so a verifier can diff it
    against the native `tile+0x25c3` / `tile+0x2647` recorded by
    `spi_emu.py --intra-trace`. Purely observational: nothing here reads it back.

    `subblock_tap(tile_index, row)` does the same one level down, per sub-block:
    the two reference arrays, the prediction and the reconstructed values, which
    line up with the trace's `refs_a`/`refs_b`/`pred`/`out`.
    """
    _header, payload = split_spi(data)
    image = parse_image_header(data[4:])
    tile_cols = (image.width + TILE - 1) // TILE
    tile_rows = (image.height + TILE - 1) // TILE
    planes, _info = plane_count_for(image.color_index)
    chunks = find_tile_chunks(payload, tile_rows, image.tile_rows_hint)

    out: dict[tuple[int, int], bytes] = {}
    palette_state = [PaletteState() for _ in range(planes)]
    frame = Frame(tile_cols, tile_rows)
    intra_modes = ModeMap(tile_cols, tile_rows)
    tables = coefficient_tables()
    # Which frame planes a pass writes: pass 0 carries R/G/B, pass 1 the alpha.
    components_of = {0: (0, 1, 2), 1: (3,)}

    for chunk in chunks:
        br = BitReader(payload[chunk.offset :])
        parse_tile_header(br)
        for plane in range(planes):
            for local in range(tile_cols * chunk.rows):
                index = chunk.index * image.tile_rows_hint * tile_cols + local
                mode = read_tile_mode(br)
                blocks = Blocks()
                px, py = (index % tile_cols) * TILE, (index // tile_cols) * TILE

                if mode == 4 and plane == 0:
                    st = palette_state[plane]
                    _note, st.entries, st.index_width = consume_mode4_palette(
                        br, st.entries, st.index_width, st
                    )
                    reconstruct_mode4(blocks, st)
                else:
                    from pysdocx.spi.parse import consume_known_mode_payload

                    first_row = local < tile_cols
                    state = {
                        "mode_contexts": (contexts or {}).get(index),
                        "mode_map": intra_modes,
                        "tile_x": index % tile_cols,
                        "tile_y": index // tile_cols,
                        "chunk_first_row": first_row,
                        # The two quantiser levels the tile picks between; see
                        # FUN_001ce290's bit in consume_known_mode_payload.
                        "quant_field_03": chunk.header.field_03,
                        "quant_field_04": chunk.header.field_04,
                    }
                    _note, motion, raw = consume_known_mode_payload(
                        br, mode, plane, strict=True, state=state
                    )
                    if mode == 0:
                        motion = mode0_motion(index % tile_cols)
                    # The row above is only there past the first row of a chunk.
                    top_available = py > 0 and not first_row
                    if mode == 5:
                        # Blocchi grezzi: FUN_001cee5c / FUN_001cf19c leggono
                        # 3x256 byte (plane 0) o 1x256 (plane 1) dopo un rewind al
                        # byte, e la ricostruzione e' il blit normale
                        # (`FUN_001c1c00`, lo stesso di mode 2 e 4). Il parser li
                        # produceva gia': erano solo buttati via, e i tile
                        # uscivano neri. Rari -- 13 in tutto il corpus -- e
                        # nessuno nei primi cinque riferimenti.
                        if plane == 0:
                            for component in range(3):
                                blocks.data[component] = bytearray(raw[component])
                        else:
                            blocks.data[3] = bytearray(raw[0])
                    elif mode == 2 and plane == 0:
                        for component, symbols in enumerate(state["symbol_blocks"]):
                            above = mode2_context(
                                frame.planes[component], frame.width, px, py, top_available
                            )
                            blocks.data[component] = bytearray(
                                reconstruct_mode2(list(symbols), above)
                            )
                    elif mode == 3 and plane == 1:
                        above, leftcol = tile_context(
                            frame.planes[3], frame.width, px, py, top_available
                        )
                        if context_tap is not None:
                            context_tap(index, above, leftcol,
                                        {"top": top_available, "left": px > 0,
                                         "px": px, "py": py})
                        reconstruct_mode3(
                            blocks.data[3],
                            [c for c in state.get("mode3_blocks", []) if c["band"] == 3],
                            above,
                            leftcol,
                            tables,
                            tap=(None if subblock_tap is None
                                 else lambda row, i=index: subblock_tap(i, row)),
                        )
                    elif mode == 3 and plane == 0:
                        # The three colour bands take a different driver:
                        # FUN_001d5f44 instead of FUN_001d5abc, in int16, with a
                        # dequantisation step (quant 23 here, 0 on the alpha) and
                        # a colour transform at the end. Same intra families.
                        reconstruct_mode3_plane0(
                            blocks.data,
                            [c for c in state.get("mode3_blocks", []) if c["band"] < 3],
                            plane0_tile_context(frame, px, py, top_available),
                            tables,
                            dequant_tables(),
                        )
                out[(plane, index)] = blocks.as_bytes()

                if mode in (0, 1):
                    # Both vectors are derived now -- 2501/2501 match the native
                    # ones, so no trace is needed.
                    dx, dy = motion
                    for component in components_of[plane]:
                        frame.copy_region(component, px - dx, py - dy, px, py)
                else:
                    for component in components_of[plane]:
                        source = component if plane == 0 else 3
                        frame.blit_block(component, px, py, blocks.data[source])
            br.align_to_next_byte()

    return out, {
        "width": image.width,
        "height": image.height,
        "tile_cols": tile_cols,
        "tile_rows": tile_rows,
        "planes": planes,
    }, frame


def load_motion(blocks_path: Path) -> dict[tuple[int, int], tuple[int, int]]:
    """Native motion vectors per tile, out of the block trace index."""
    with blocks_path.with_suffix(".csv").open() as f:
        return {
            (int(r["plane"]), int(r["tile_idx"])): (int(r["motion_dx"]), int(r["motion_dy"]))
            for r in csv.DictReader(f)
        }


def load_above(blocks_path: Path) -> dict[tuple[int, int], bytes]:
    """The 4x16 row-above bytes per tile, out of the native block trace."""
    with blocks_path.with_suffix(".csv").open() as f:
        index = list(csv.DictReader(f))
    raw = blocks_path.read_bytes()
    stride = COMPONENTS * (BLOCK_PIXELS + TILE)
    base = COMPONENTS * BLOCK_PIXELS
    out = {}
    for position, row in enumerate(index):
        start = position * stride + base
        out[(int(row["plane"]), int(row["tile_idx"]))] = raw[start : start + COMPONENTS * TILE]
    return out


def verify_blocks(
    produced: dict[tuple[int, int], bytes], blocks_path: Path
) -> bool:
    """Compare the reconstructed blocks against the native ones, per tile."""
    index_path = blocks_path.with_suffix(".csv")
    with index_path.open() as f:
        index = list(csv.DictReader(f))
    raw = blocks_path.read_bytes()
    stride = COMPONENTS * (BLOCK_PIXELS + TILE)  # blocks, then the row-above context

    stats: dict[int, dict] = {}
    for position, row in enumerate(index):
        plane, mode = int(row["plane"]), int(row["mode"])
        key = (plane, int(row["tile_idx"]))
        native = raw[position * stride : (position + 1) * stride]
        st = stats.setdefault((plane, mode), {"n": 0, "ok": 0})
        st["n"] += 1
        mine = produced.get(key)
        if mine is None:
            continue
        # Only the components a mode actually fills are meaningful: plane 0
        # carries R/G/B, plane 1 only the alpha block.
        span = (
            slice(0, 3 * BLOCK_PIXELS)
            if plane == 0
            else slice(3 * BLOCK_PIXELS, COMPONENTS * BLOCK_PIXELS)
        )
        if mine[span] == native[span]:
            st["ok"] += 1

    print("  plane mode   tiles      ok   status")
    total = total_ok = 0
    for (plane, mode), st in sorted(stats.items()):
        status = "EXACT" if st["ok"] == st["n"] else ("none" if not st["ok"] else "PARTIAL")
        print(f"    {plane}    {mode}  {st['n']:6d}  {st['ok']:6d}   {status}")
        total += st["n"]
        total_ok += st["ok"]
    print(f"  TOTAL: {total_ok}/{total} tiles reconstruct the native blocks exactly")
    return total_ok == total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--only", help="substring filter for member names")
    ap.add_argument("--context-csv", type=Path, help="FUN_001d4000 context oracle")
    ap.add_argument("--verify-blocks", type=Path, help="native block trace to check against")
    ap.add_argument("--png", type=Path, help="write the decoded image")
    ap.add_argument("--compare", type=Path, help="ground-truth PNG to diff against")
    args = ap.parse_args()

    contexts = load_mode_contexts(args.context_csv) if args.context_csv else None
    ok = True
    for name, data in iter_member_bytes(args.path):
        if args.only and args.only not in name:
            continue
        print(f"\n{name}")
        above = load_above(args.verify_blocks) if args.verify_blocks else None
        motion = load_motion(args.verify_blocks) if args.verify_blocks else None
        produced, info, frame = decode(data, contexts, above, motion)
        print(f"  {info['width']}x{info['height']} tiles={info['tile_cols']}x{info['tile_rows']}")
        if args.verify_blocks:
            ok &= verify_blocks(produced, args.verify_blocks)
        if args.png:
            from PIL import Image

            rgba = frame.to_rgba(info["width"], info["height"])
            Image.frombytes("RGBA", (info["width"], info["height"]), rgba).save(args.png)
            print(f"  wrote {args.png}")
        if args.compare:
            from PIL import Image

            gt = Image.open(args.compare).convert("RGBA").tobytes()
            mine = frame.to_rgba(info["width"], info["height"])
            diff = sum(1 for i in range(0, len(gt), 4) if gt[i:i+4] != mine[i:i+4])
            total = len(gt) // 4
            print(f"  COMPARE: {diff}/{total} pixels differ ({diff/total*100:.1f}%)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
