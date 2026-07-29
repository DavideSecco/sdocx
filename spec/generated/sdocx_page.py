# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
import sdocx_object_header


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxPage(KaitaiStruct):
    """A `.sdocx` archive's `<uuid>.page` member. Each page is one `.page` file.

    The header (bytes `0 .. base`) is a sequential structure: `base` (the
    layer-tree start offset, alias `page_end_offset`), `flex_offset`, two
    variable-length bitfields, page geometry/uuid/timestamps, then a run of
    optional "flex" fields gated by one `field_flags` bit each, in bit order,
    starting exactly at `flex_offset`. It is followed by the layer/object tree
    at `base`, and a trailing page hash + SDK signature.

    Field names cross-referenced from squ1dd13/sdocx2pdf (MIT) — `page.rs`,
    `page/header.rs` — re-validated field-by-field on the local corpus before
    adoption here (zero counterexamples, 220/220 pages,
    spec/tools/validate_page_header.py; see docs/format/xref-sdocx2pdf.md and
    docs/format/container/page/README.md). Reference Python parser:
    pysdocx/page_header.py (this .ksy mirrors it field-for-field).

    The layer/object tree is structural: object entries carry raw type, child
    count, and blob size, and recursive children follow the blob. The blob itself
    begins with the common object header, modeled by `sdocx_object_header` via a
    substream. Payload internals (strokes, semantic shape/image/text markers) stay
    procedural and are documented in the companion Markdown:

      - layer/object tree     -> docs/format/container/page/README.md
      - common object header  -> docs/format/container/page/object-header.md
      - payload geometry       -> docs/format/container/page/payload-geometry.md
      - strokes                -> docs/format/container/page/strokes.md
      - shapes/images/text     -> docs/format/container/page/object-types.md

    Two fields deliberately not resolved further here (still Marker/Unknown,
    see docs/format/unknowns.md): `template_type` ids 10/12-15 are named from
    sdocx2pdf only, not yet grounded against a hand-labeled sample of our own;
    and `custom_object`'s `trailing_raw` (constant 8 bytes on the corpus,
    semantics Unknown — sdocx2pdf's own schema doesn't have this field).
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxPage, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.base = self._io.read_u4le()
        self.flex_offset = self._io.read_u4le()
        self.property_flags = SdocxPage.VarBitfield(self._io, self, self._root)
        self.field_flags = SdocxPage.VarBitfield(self._io, self, self._root)
        self.orientation = self._io.read_u4le()
        self.width = self._io.read_u4le()
        self.height = self._io.read_u4le()
        self.offset_x = self._io.read_u4le()
        self.offset_y = self._io.read_u4le()
        self.uuid = SdocxPage.ShortUtf16(self._io, self, self._root)
        self.modified_time_us = self._io.read_s8le()
        self.format_version = self._io.read_u4le()
        self.min_format_version = self._io.read_u4le()
        if self.has_drawn_rect:
            pass
            self.drawn_rect = []
            for i in range(4):
                self.drawn_rect.append(self._io.read_f8le())


        if self.has_tags:
            pass
            self.tags = SdocxPage.TagList(self._io, self, self._root)

        if self.has_template_uri:
            pass
            self.template_uri = SdocxPage.ShortUtf16(self._io, self, self._root)

        if self.has_background_image_id:
            pass
            self.background_image_id = self._io.read_s4le()

        if self.has_background_image_mode:
            pass
            self.background_image_mode = self._io.read_u4le()

        if self.has_background_colour:
            pass
            self.background_colour = self._io.read_bytes(4)

        if self.has_background_width:
            pass
            self.background_width = self._io.read_u4le()

        if self.has_background_rotation:
            pass
            self.background_rotation = self._io.read_u4le()

        if self.has_pdf_data_items:
            pass
            self.pdf_data_items = SdocxPage.PdfDataItems(self.format_version, self._io, self, self._root)

        if self.has_template_type:
            pass
            self.template_type = self._io.read_u4le()

        if self.has_canvas_cache_map:
            pass
            self.canvas_cache_map = SdocxPage.CanvasCacheMap(self._io, self, self._root)

        if self.has_imported_data_height:
            pass
            self.imported_data_height = self._io.read_u4le()

        if self.has_theme:
            pass
            self.theme = self._io.read_u4le()

        if self.has_recognised_data_modified_time:
            pass
            self.recognised_data_modified_time_us = self._io.read_s8le()

        if self.has_stroke_recognition_data:
            pass
            self.stroke_recognition_data = SdocxPage.OpaqueBlobList(self._io, self, self._root)

        if self.has_custom_objects:
            pass
            self.custom_objects = SdocxPage.CustomObjectList(self._io, self, self._root)



    def _fetch_instances(self):
        pass
        self.property_flags._fetch_instances()
        self.field_flags._fetch_instances()
        self.uuid._fetch_instances()
        if self.has_drawn_rect:
            pass
            for i in range(len(self.drawn_rect)):
                pass


        if self.has_tags:
            pass
            self.tags._fetch_instances()

        if self.has_template_uri:
            pass
            self.template_uri._fetch_instances()

        if self.has_background_image_id:
            pass

        if self.has_background_image_mode:
            pass

        if self.has_background_colour:
            pass

        if self.has_background_width:
            pass

        if self.has_background_rotation:
            pass

        if self.has_pdf_data_items:
            pass
            self.pdf_data_items._fetch_instances()

        if self.has_template_type:
            pass

        if self.has_canvas_cache_map:
            pass
            self.canvas_cache_map._fetch_instances()

        if self.has_imported_data_height:
            pass

        if self.has_theme:
            pass

        if self.has_recognised_data_modified_time:
            pass

        if self.has_stroke_recognition_data:
            pass
            self.stroke_recognition_data._fetch_instances()

        if self.has_custom_objects:
            pass
            self.custom_objects._fetch_instances()

        _ = self.footer_signature
        if hasattr(self, '_m_footer_signature'):
            pass

        _ = self.page_hash
        if hasattr(self, '_m_page_hash'):
            pass

        _ = self.tree
        if hasattr(self, '_m_tree'):
            pass
            self._m_tree._fetch_instances()


    class CanvasCacheEntry(KaitaiStruct):
        """49 bytes total (4-byte key + 45-byte entry)."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.CanvasCacheEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = self._io.read_u4le()
            self.file_id = self._io.read_u4le()
            self.width = self._io.read_u4le()
            self.height = self._io.read_u4le()
            self.is_dark_mode = self._io.read_u1()
            self.background_colour = self._io.read_bytes(4)
            self.version = []
            for i in range(3):
                self.version.append(self._io.read_u4le())

            self.cache_version = self._io.read_u4le()
            self.property = self._io.read_u4le()
            self.locale_list_id = self._io.read_u4le()
            self.system_font_path_hash = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            for i in range(len(self.version)):
                pass



    class CanvasCacheMap(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.CanvasCacheMap, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.entry_count = self._io.read_u4le()
            self.entry_size = self._io.read_u2le()
            if self.entry_size == 49:
                pass
                self.entries = []
                for i in range(self.entry_count):
                    self.entries.append(SdocxPage.CanvasCacheEntry(self._io, self, self._root))


            if self.entry_size != 49:
                pass
                self.raw_entries = self._io.read_bytes(self.entry_count * self.entry_size)



        def _fetch_instances(self):
            pass
            if self.entry_size == 49:
                pass
                for i in range(len(self.entries)):
                    pass
                    self.entries[i]._fetch_instances()


            if self.entry_size != 49:
                pass



    class CustomObject(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.CustomObject, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.object_type = self._io.read_u4le()
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxPage.CustomObjectBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class CustomObjectBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.CustomObjectBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.reserved = self._io.read_u4le()
            self.property_flags = SdocxPage.VarBitfield(self._io, self, self._root)
            self.field_flags = SdocxPage.VarBitfield(self._io, self, self._root)
            self.uuid = SdocxPage.ShortUtf8(self._io, self, self._root)
            self.attached_files = SdocxPage.StringToU4Map(self._io, self, self._root)
            self.custom_data = SdocxPage.StringToStringMap(self._io, self, self._root)
            self.rect = []
            for i in range(4):
                self.rect.append(self._io.read_f8le())

            self.trailing_raw = self._io.read_bytes_full()


        def _fetch_instances(self):
            pass
            self.property_flags._fetch_instances()
            self.field_flags._fetch_instances()
            self.uuid._fetch_instances()
            self.attached_files._fetch_instances()
            self.custom_data._fetch_instances()
            for i in range(len(self.rect)):
                pass



    class CustomObjectList(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.CustomObjectList, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u4le()
            self.objects = []
            for i in range(self.count):
                self.objects.append(SdocxPage.CustomObject(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.objects)):
                pass
                self.objects[i]._fetch_instances()



    class Layer(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.Layer, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.layer_prefix = self._io.read_u4le()
            self.next_offset = self._io.read_u4le()
            self.flag1 = self._io.read_u1()
            self.flag2 = self._io.read_u1()
            self.flag3 = self._io.read_u1()
            self.content_flags = self._io.read_u1()
            self.layer_flags = self._io.read_u4le()
            if self.content_flags & 1 != 0:
                pass
                self.content_01 = self._io.read_u1()

            if self.content_flags & 2 != 0:
                pass
                self.content_02 = self._io.read_bytes(4)

            if self.content_flags & 4 != 0:
                pass
                self.content_04_text = SdocxPage.Utf16String(self._io, self, self._root)

            if self.content_flags & 8 != 0:
                pass
                self.layer_uuid = SdocxPage.Utf16String(self._io, self, self._root)

            if self.content_flags & 16 != 0:
                pass
                self.modified_time = self._io.read_s8le()

            if self.content_flags & 32 != 0:
                pass
                self.content_20 = self._io.read_bytes(4)

            self.object_count = self._io.read_u4le()
            self.objects = []
            for i in range(self.object_count):
                self.objects.append(SdocxPage.ObjectEntry(self._io, self, self._root))

            self.layer_hash = self._io.read_bytes(32)


        def _fetch_instances(self):
            pass
            if self.content_flags & 1 != 0:
                pass

            if self.content_flags & 2 != 0:
                pass

            if self.content_flags & 4 != 0:
                pass
                self.content_04_text._fetch_instances()

            if self.content_flags & 8 != 0:
                pass
                self.layer_uuid._fetch_instances()

            if self.content_flags & 16 != 0:
                pass

            if self.content_flags & 32 != 0:
                pass

            for i in range(len(self.objects)):
                pass
                self.objects[i]._fetch_instances()



    class LongUtf8(KaitaiStruct):
        """A u32 byte count followed by that many UTF-8 bytes."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.LongUtf8, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.byte_len = self._io.read_u4le()
            self.value = (self._io.read_bytes(self.byte_len)).decode(u"UTF-8")


        def _fetch_instances(self):
            pass


    class ObjectEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.ObjectEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.raw_type = self._io.read_u1()
            self.child_count = self._io.read_s2le()
            self.blob_size = self._io.read_u4le()
            self._raw_blob = self._io.read_bytes(self.blob_size)
            _io__raw_blob = KaitaiStream(BytesIO(self._raw_blob))
            self.blob = sdocx_object_header.SdocxObjectHeader(_io__raw_blob)
            self.children = []
            for i in range((self.child_count if self.child_count > 0 else 0)):
                self.children.append(SdocxPage.ObjectEntry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            self.blob._fetch_instances()
            for i in range(len(self.children)):
                pass
                self.children[i]._fetch_instances()



    class OpaqueBlob(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.OpaqueBlob, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self.data = self._io.read_bytes(self.size)


        def _fetch_instances(self):
            pass


    class OpaqueBlobList(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.OpaqueBlobList, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u4le()
            self.blobs = []
            for i in range(self.count):
                self.blobs.append(SdocxPage.OpaqueBlob(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.blobs)):
                pass
                self.blobs[i]._fetch_instances()



    class PageTree(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.PageTree, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.layer_count = self._io.read_u2le()
            self.current_layer_index = self._io.read_u2le()
            self.layers = []
            for i in range(self.layer_count):
                self.layers.append(SdocxPage.Layer(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.layers)):
                pass
                self.layers[i]._fetch_instances()


        @property
        def has_objects(self):
            """Current corpus has one layer; its declared object count gates the preamble content_bbox."""
            if hasattr(self, '_m_has_objects'):
                return self._m_has_objects

            self._m_has_objects =  ((len(self.layers) > 0) and (self.layers[0].object_count > 0))
            return getattr(self, '_m_has_objects', None)


    class PdfDataItems(KaitaiStruct):
        def __init__(self, format_version, _io, _parent=None, _root=None):
            super(SdocxPage.PdfDataItems, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.format_version = format_version
            self._read()

        def _read(self):
            self.count = self._io.read_u2le()
            self.items = []
            for i in range(self.count):
                self.items.append(SdocxPage.PdfPageItem(self.format_version, self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.items)):
                pass
                self.items[i]._fetch_instances()



    class PdfPageItem(KaitaiStruct):
        """`rect` is 4×f64 pre-2034 format versions, else 4×i32 (both variants
        agree with page_pdf_template's media/page indices on every corpus page
        where both mechanisms fire).
        """
        def __init__(self, format_version, _io, _parent=None, _root=None):
            super(SdocxPage.PdfPageItem, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.format_version = format_version
            self._read()

        def _read(self):
            self.file_id = self._io.read_u4le()
            self.page_index = self._io.read_u4le()
            if self.format_version < 2034:
                pass
                self.rect_f64 = []
                for i in range(4):
                    self.rect_f64.append(self._io.read_f8le())


            if self.format_version >= 2034:
                pass
                self.rect_i32 = []
                for i in range(4):
                    self.rect_i32.append(self._io.read_s4le())




        def _fetch_instances(self):
            pass
            if self.format_version < 2034:
                pass
                for i in range(len(self.rect_f64)):
                    pass


            if self.format_version >= 2034:
                pass
                for i in range(len(self.rect_i32)):
                    pass




    class ShortUtf16(KaitaiStruct):
        """A u16 character count followed by that many UTF-16LE code units."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.ShortUtf16, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class ShortUtf8(KaitaiStruct):
        """A u16 BYTE count followed by that many UTF-8 bytes (object uuids in this region)."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.ShortUtf8, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.byte_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.byte_len)).decode(u"UTF-8")


        def _fetch_instances(self):
            pass


    class StringToStringEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.StringToStringEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxPage.LongUtf8(self._io, self, self._root)
            self.value = SdocxPage.LongUtf8(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            self.key._fetch_instances()
            self.value._fetch_instances()


    class StringToStringMap(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.StringToStringMap, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u4le()
            self.entries = []
            for i in range(self.count):
                self.entries.append(SdocxPage.StringToStringEntry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class StringToU4Entry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.StringToU4Entry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxPage.LongUtf8(self._io, self, self._root)
            self.value = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.key._fetch_instances()


    class StringToU4Map(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.StringToU4Map, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u4le()
            self.entries = []
            for i in range(self.count):
                self.entries.append(SdocxPage.StringToU4Entry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class TagList(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.TagList, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u2le()
            self.tags = []
            for i in range(self.count):
                self.tags.append(SdocxPage.ShortUtf16(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.tags)):
                pass
                self.tags[i]._fetch_instances()



    class Utf16String(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.Utf16String, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class VarBitfield(KaitaiStruct):
        """`[u8 n_bytes][n-byte little-endian bitfield]`, n <= 4. On the corpus n
        is 1 (property_flags) or 4 (field_flags).
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.VarBitfield, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.len = self._io.read_u1()
            if self.len >= 1:
                pass
                self.b0 = self._io.read_u1()

            if self.len >= 2:
                pass
                self.b1 = self._io.read_u1()

            if self.len >= 3:
                pass
                self.b2 = self._io.read_u1()

            if self.len >= 4:
                pass
                self.b3 = self._io.read_u1()



        def _fetch_instances(self):
            pass
            if self.len >= 1:
                pass

            if self.len >= 2:
                pass

            if self.len >= 3:
                pass

            if self.len >= 4:
                pass


        @property
        def value(self):
            if hasattr(self, '_m_value'):
                return self._m_value

            self._m_value = (((self.b0 if self.len >= 1 else 0) | (self.b1 << 8 if self.len >= 2 else 0)) | (self.b2 << 16 if self.len >= 3 else 0)) | (self.b3 << 24 if self.len >= 4 else 0)
            return getattr(self, '_m_value', None)


    @property
    def footer_signature(self):
        """Trailing marker; always "Page for SAMSUNG S-Pen SDK"."""
        if hasattr(self, '_m_footer_signature'):
            return self._m_footer_signature

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 26)
        self._m_footer_signature = (self._io.read_bytes(26)).decode(u"ASCII")
        self._io.seek(_pos)
        return getattr(self, '_m_footer_signature', None)

    @property
    def has_background_colour(self):
        if hasattr(self, '_m_has_background_colour'):
            return self._m_has_background_colour

        self._m_has_background_colour = self.field_flags.value >> 5 & 1 != 0
        return getattr(self, '_m_has_background_colour', None)

    @property
    def has_background_image_id(self):
        if hasattr(self, '_m_has_background_image_id'):
            return self._m_has_background_image_id

        self._m_has_background_image_id = self.field_flags.value >> 3 & 1 != 0
        return getattr(self, '_m_has_background_image_id', None)

    @property
    def has_background_image_mode(self):
        if hasattr(self, '_m_has_background_image_mode'):
            return self._m_has_background_image_mode

        self._m_has_background_image_mode = self.field_flags.value >> 4 & 1 != 0
        return getattr(self, '_m_has_background_image_mode', None)

    @property
    def has_background_rotation(self):
        if hasattr(self, '_m_has_background_rotation'):
            return self._m_has_background_rotation

        self._m_has_background_rotation = self.field_flags.value >> 7 & 1 != 0
        return getattr(self, '_m_has_background_rotation', None)

    @property
    def has_background_width(self):
        if hasattr(self, '_m_has_background_width'):
            return self._m_has_background_width

        self._m_has_background_width = self.field_flags.value >> 6 & 1 != 0
        return getattr(self, '_m_has_background_width', None)

    @property
    def has_canvas_cache_map(self):
        if hasattr(self, '_m_has_canvas_cache_map'):
            return self._m_has_canvas_cache_map

        self._m_has_canvas_cache_map = self.field_flags.value >> 10 & 1 != 0
        return getattr(self, '_m_has_canvas_cache_map', None)

    @property
    def has_custom_objects(self):
        if hasattr(self, '_m_has_custom_objects'):
            return self._m_has_custom_objects

        self._m_has_custom_objects = self.field_flags.value >> 18 & 1 != 0
        return getattr(self, '_m_has_custom_objects', None)

    @property
    def has_drawn_rect(self):
        if hasattr(self, '_m_has_drawn_rect'):
            return self._m_has_drawn_rect

        self._m_has_drawn_rect = self.field_flags.value >> 0 & 1 != 0
        return getattr(self, '_m_has_drawn_rect', None)

    @property
    def has_imported_data_height(self):
        if hasattr(self, '_m_has_imported_data_height'):
            return self._m_has_imported_data_height

        self._m_has_imported_data_height = self.field_flags.value >> 11 & 1 != 0
        return getattr(self, '_m_has_imported_data_height', None)

    @property
    def has_pdf_data_items(self):
        if hasattr(self, '_m_has_pdf_data_items'):
            return self._m_has_pdf_data_items

        self._m_has_pdf_data_items = self.field_flags.value >> 8 & 1 != 0
        return getattr(self, '_m_has_pdf_data_items', None)

    @property
    def has_recognised_data_modified_time(self):
        if hasattr(self, '_m_has_recognised_data_modified_time'):
            return self._m_has_recognised_data_modified_time

        self._m_has_recognised_data_modified_time = self.field_flags.value >> 15 & 1 != 0
        return getattr(self, '_m_has_recognised_data_modified_time', None)

    @property
    def has_stroke_recognition_data(self):
        if hasattr(self, '_m_has_stroke_recognition_data'):
            return self._m_has_stroke_recognition_data

        self._m_has_stroke_recognition_data = self.field_flags.value >> 16 & 1 != 0
        return getattr(self, '_m_has_stroke_recognition_data', None)

    @property
    def has_tags(self):
        if hasattr(self, '_m_has_tags'):
            return self._m_has_tags

        self._m_has_tags = self.field_flags.value >> 1 & 1 != 0
        return getattr(self, '_m_has_tags', None)

    @property
    def has_template_type(self):
        if hasattr(self, '_m_has_template_type'):
            return self._m_has_template_type

        self._m_has_template_type = self.field_flags.value >> 9 & 1 != 0
        return getattr(self, '_m_has_template_type', None)

    @property
    def has_template_uri(self):
        if hasattr(self, '_m_has_template_uri'):
            return self._m_has_template_uri

        self._m_has_template_uri = self.field_flags.value >> 2 & 1 != 0
        return getattr(self, '_m_has_template_uri', None)

    @property
    def has_theme(self):
        if hasattr(self, '_m_has_theme'):
            return self._m_has_theme

        self._m_has_theme = self.field_flags.value >> 12 & 1 != 0
        return getattr(self, '_m_has_theme', None)

    @property
    def has_unhandled_field_bits(self):
        """True if any field bit outside the modeled set (0-12, 15, 16, 18) is
        set; the sequence after min_format_version would then be misaligned.
        Zero on the corpus.
        """
        if hasattr(self, '_m_has_unhandled_field_bits'):
            return self._m_has_unhandled_field_bits

        self._m_has_unhandled_field_bits = self.field_flags.value & 4294598656 != 0
        return getattr(self, '_m_has_unhandled_field_bits', None)

    @property
    def page_hash(self):
        """32-byte page content hash. This is exactly the value pageIdInfo.dat stores
        as the page's `page_hash` (the manifest copies it), which is why that
        manifest hash is not a digest of the raw .page member. Sits immediately
        before the footer signature.
        """
        if hasattr(self, '_m_page_hash'):
            return self._m_page_hash

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 58)
        self._m_page_hash = self._io.read_bytes(32)
        self._io.seek(_pos)
        return getattr(self, '_m_page_hash', None)

    @property
    def tree(self):
        """Layer/object tree rooted at the header's `base` offset."""
        if hasattr(self, '_m_tree'):
            return self._m_tree

        _pos = self._io.pos()
        self._io.seek(self.base)
        self._m_tree = SdocxPage.PageTree(self._io, self, self._root)
        self._io.seek(_pos)
        return getattr(self, '_m_tree', None)


