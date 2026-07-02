"""Reusable toolkit for reverse-engineering the .sdocx format.

Mirrors the validated Rust parser in crates/sdocx (decode.rs, page.rs) so
findings can be checked from the shell or a notebook before being ported back.
"""

from pysdocx.container import (
    bg_color_from_note,
    list_attachments,
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
    decode_outline,
    flatten_outline,
    page_template,
    parse_page,
    parse_page_tree,
    parse_shapes,
    parse_shapes_from_objects,
    parse_text_boxes_from_objects,
    scan_arrows,
    scan_drawings,
    scan_drawings_from_objects,
    scan_images,
    scan_images_from_objects,
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
    "list_attachments",
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
    "parse_page_tree",
    "page_template",
    "GRID_SPACING",
    "GRID_ORIGIN",
    "scan_shapes",
    "parse_shapes",
    "parse_shapes_from_objects",
    "parse_text_boxes_from_objects",
    "scan_arrows",
    "decode_outline",
    "flatten_outline",
    "scan_images",
    "scan_images_from_objects",
    "scan_drawings",
    "scan_drawings_from_objects",
    "render_document",
    "render_page",
]

# Rendering pulls in matplotlib/numpy/Pillow; import it lazily so `import pysdocx`
# (parser-only use) stays lightweight. Access `pysdocx.render_document` / `render_page`
# to trigger the import, or import from `pysdocx.render` directly.
_RENDER_EXPORTS = {"render_document", "render_page"}


def __getattr__(name):
    if name in _RENDER_EXPORTS:
        from pysdocx import render

        return getattr(render, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
