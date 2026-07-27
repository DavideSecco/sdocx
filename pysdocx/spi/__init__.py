"""Decoder for Samsung's `.spi` ("Maetel") raster, reverse-engineered.

Samsung Notes stores some page objects as `.spi`, and also keeps its **own
full-resolution render of every page** as `media/<n>@page_<id>.spi`. Nothing
else can read them: without this decoder the "convert to math" formula object
cannot be drawn at all, and Samsung's per-page renders -- a rendering oracle for
the whole corpus -- stay out of reach.

    from pysdocx.spi import decode_rgba

    rgba, width, height = decode_rgba(spi_bytes)

Two layers, mirroring the native decoder:

* `parse` -- the bitstream: wrapper, `AA01`/`AA02` chunks, the per-tile mode VLC
  and each mode's payload. Bit-exact against the native decoder on every tile of
  the corpus;
* `decode` -- reconstruction: motion copies, palette expansion, the symbol
  coder, and the intra coder (references, directional/planar prediction, inverse
  transforms, residual, YCoCg-R colour transform).

**Verified**: every `.spi` member of the 28-archive corpus -- 220 members,
800,698,496 pixels -- decodes **byte-identically** to Samsung's own decoder run
under emulation. `tests/test_spi_decode.py` gates the members that live in the
tracked part of the corpus against committed hashes, with no Samsung binary in
the loop.

`tables.py` is generated: the static tables live in Samsung's `libSPenBase.so`
and were extracted **once, offline** into Python constants, each carrying its
provenance. Neither this package nor anything else in the repo reads that binary
at runtime, and none of its bytes are vendored here. The reverse engineering
itself -- the emulator oracle, the decompiled sources, the per-call verification
gates -- stays outside the repo, in the gitignored `apk-re/`.
"""

from pysdocx.spi.decode import decode as _decode


def decode_rgba(data: bytes) -> tuple[bytes, int, int]:
    """Decode one `.spi` member to tightly packed RGBA, 8 bits per channel.

    `data` is the whole member, wrapper included, as stored in the archive.
    """
    _blocks, info, frame = _decode(data)
    width, height = info["width"], info["height"]
    return frame.to_rgba(width, height), width, height


def spi_size(data: bytes) -> tuple[int, int]:
    """(width, height) from the header, without decoding a single pixel."""
    from pysdocx.spi.parse import parse_image_header

    image = parse_image_header(data[4:])
    return image.width, image.height


__all__ = ["decode_rgba", "spi_size"]
