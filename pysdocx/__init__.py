"""Reusable toolkit for reverse-engineering the .sdocx format.

Mirrors the validated Rust parser in crates/sdocx (decode.rs, page.rs) so
findings can be checked from the shell or a notebook before being ported back.
"""

from pysdocx.container import (
    bg_color_from_note,
    list_pages,
    load_bg_color,
    load_media_by_index,
    load_note,
    load_page,
    load_page_with_bg,
    raster_media_indices,
)
from pysdocx.note import parse_tables, parse_typed_text
from pysdocx.dump import dump_container, hexdump
from pysdocx.ink import color_hex, decode_coordinates, decode_sign_mag, decode_trailing, extract_color_and_width
from pysdocx.page import (
    GRID_ORIGIN,
    GRID_SPACING,
    page_template,
    parse_page,
    scan_drawings,
    scan_images,
    scan_shapes,
)

__all__ = [
    "list_pages",
    "load_bg_color",
    "bg_color_from_note",
    "load_page",
    "load_page_with_bg",
    "load_media_by_index",
    "load_note",
    "raster_media_indices",
    "parse_typed_text",
    "parse_tables",
    "hexdump",
    "dump_container",
    "decode_coordinates",
    "decode_sign_mag",
    "decode_trailing",
    "extract_color_and_width",
    "color_hex",
    "parse_page",
    "page_template",
    "GRID_SPACING",
    "GRID_ORIGIN",
    "scan_shapes",
    "scan_images",
    "scan_drawings",
]
