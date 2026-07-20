# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
import sdocx_web_object
import sdocx_table_object


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxTextWrapper(KaitaiStruct):
    """Complete inheritance chain used by note.note title/body Text blobs and by
    raw type-2 page text boxes:

      ObjectBase(type 0) -> ShapeBase(type 6) -> Shape(type 7) -> Text(type 2)

    Every component is an inclusive-length ObjectHeader frame.  Shape's flex
    offset lands directly on its text_core::Common frame, so the main rich-text
    payload is parsed without marker scanning.  Page text boxes may append one
    32-byte hash-like value after Text; note.note title/body blobs end at Text.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxTextWrapper, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.object_base = SdocxTextWrapper.ObjectBaseFrame(self._io, self, self._root)
        self.shape_base = SdocxTextWrapper.OpaqueFrame(6, self._io, self, self._root)
        self.shape = SdocxTextWrapper.ShapeFrame(self.object_base.body.format_version, self._io, self, self._root)
        self.text = SdocxTextWrapper.TextFrame(self._io, self, self._root)
        self.trailing_hash_like = self._io.read_bytes(self._io.size() - self._io.pos())


    def _fetch_instances(self):
        pass
        self.object_base._fetch_instances()
        self.shape_base._fetch_instances()
        self.shape._fetch_instances()
        self.text._fetch_instances()

    class Bitfield(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.Bitfield, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.n_bytes = self._io.read_u1()
            self.raw = self._io.read_bytes(self.n_bytes)


        def _fetch_instances(self):
            pass

        @property
        def value(self):
            if hasattr(self, '_m_value'):
                return self._m_value

            self._m_value = ((KaitaiStream.byte_array_index(self.raw, 0) + (KaitaiStream.byte_array_index(self.raw, 1) << 8 if self.n_bytes > 1 else 0)) + (KaitaiStream.byte_array_index(self.raw, 2) << 16 if self.n_bytes > 2 else 0)) + (KaitaiStream.byte_array_index(self.raw, 3) << 24 if self.n_bytes > 3 else 0)
            return getattr(self, '_m_value', None)


    class CommonFrame(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.CommonFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_count = self._io.read_u4le()
            self.text_utf16 = (self._io.read_bytes(self.char_count * 2)).decode(u"UTF-16LE")
            self.span_count = self._io.read_u4le()
            self.spans = []
            for i in range(self.span_count):
                self.spans.append(SdocxTextWrapper.SpanRec(self._io, self, self._root))

            self.paragraph_count = self._io.read_u4le()
            self.paragraphs = []
            for i in range(self.paragraph_count):
                self.paragraphs.append(SdocxTextWrapper.ParagraphRec(self._io, self, self._root))

            self.margins = []
            for i in range(4):
                self.margins.append(self._io.read_f4le())

            self.gravity = self._io.read_u1()
            self.section_count = self._io.read_u2le()
            self.sections = []
            for i in range(self.section_count):
                self.sections.append(SdocxTextWrapper.SectionPair(self._io, self, self._root))

            self.inline_present = self._io.read_u4le()
            self.inline_zero = self._io.read_u4le()
            if self.inline_present != 0:
                pass
                self.inline_count = self._io.read_u4le()

            if self.inline_present != 0:
                pass
                self.inline_objects = []
                for i in range(self.inline_count):
                    self.inline_objects.append(SdocxTextWrapper.InlineObject(self._io, self, self._root))




        def _fetch_instances(self):
            pass
            for i in range(len(self.spans)):
                pass
                self.spans[i]._fetch_instances()

            for i in range(len(self.paragraphs)):
                pass
                self.paragraphs[i]._fetch_instances()

            for i in range(len(self.margins)):
                pass

            for i in range(len(self.sections)):
                pass
                self.sections[i]._fetch_instances()

            if self.inline_present != 0:
                pass

            if self.inline_present != 0:
                pass
                for i in range(len(self.inline_objects)):
                    pass
                    self.inline_objects[i]._fetch_instances()




    class InlineObject(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.InlineObject, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.frame_size = self._io.read_u4le()
            self._raw_frame = self._io.read_bytes(self.frame_size)
            _io__raw_frame = KaitaiStream(BytesIO(self._raw_frame))
            self.frame = SdocxTextWrapper.InlineObjectBody(_io__raw_frame, self, self._root)


        def _fetch_instances(self):
            pass
            self.frame._fetch_instances()


    class InlineObjectBody(KaitaiStruct):
        """`object_body` is decoded for the two known inline-object types (22 =
        table, 13 = web link/preview); other types (e.g. 3 = inline image)
        have no dedicated spec yet and stay opaque bytes.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.InlineObjectBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.object_size = self._io.read_u4le()
            self.object_type = self._io.read_u4le()
            _on = self.object_type
            if _on == 13:
                pass
                self._raw_object_body = self._io.read_bytes(self.object_size)
                _io__raw_object_body = KaitaiStream(BytesIO(self._raw_object_body))
                self.object_body = sdocx_web_object.SdocxWebObject(_io__raw_object_body)
            elif _on == 22:
                pass
                self._raw_object_body = self._io.read_bytes(self.object_size)
                _io__raw_object_body = KaitaiStream(BytesIO(self._raw_object_body))
                self.object_body = sdocx_table_object.SdocxTableObject(_io__raw_object_body)
            else:
                pass
                self._raw_object_body = self._io.read_bytes(self.object_size)
                _io__raw_object_body = KaitaiStream(BytesIO(self._raw_object_body))
                self.object_body = SdocxTextWrapper.OpaqueInlineBody(_io__raw_object_body, self, self._root)
            self.position = self._io.read_u4le()
            self.tail = self._io.read_bytes(self._io.size() - self._io.pos())


        def _fetch_instances(self):
            pass
            _on = self.object_type
            if _on == 13:
                pass
                self.object_body._fetch_instances()
            elif _on == 22:
                pass
                self.object_body._fetch_instances()
            else:
                pass
                self.object_body._fetch_instances()


    class ObjectBaseBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ObjectBaseBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.header = SdocxTextWrapper.ObjectHeader(self._io, self, self._root)
            self.format_version = self._io.read_u4le()
            self.uuid_len = self._io.read_u2le()
            self.uuid = (self._io.read_bytes(self.uuid_len)).decode(u"UTF-8")
            self.modified_time_us = self._io.read_s8le()
            self.bbox = []
            for i in range(4):
                self.bbox.append(self._io.read_f8le())

            self.timestamp = self._io.read_u4le()
            self.resize_mode = self._io.read_u1()
            if self.header.field_flags.value & 1 != 0:
                pass
                self.angle_deg = self._io.read_f4le()

            if self.header.field_flags.value & 8192 != 0:
                pass
                self.append_time_us = self._io.read_s8le()

            if self.header.field_flags.value & 16384 != 0:
                pass
                self.owner_page_size = []
                for i in range(2):
                    self.owner_page_size.append(self._io.read_u4le())


            if self.header.field_flags.value & 262144 != 0:
                pass
                self.pivot = []
                for i in range(2):
                    self.pivot.append(self._io.read_f8le())




        def _fetch_instances(self):
            pass
            self.header._fetch_instances()
            for i in range(len(self.bbox)):
                pass

            if self.header.field_flags.value & 1 != 0:
                pass

            if self.header.field_flags.value & 8192 != 0:
                pass

            if self.header.field_flags.value & 16384 != 0:
                pass
                for i in range(len(self.owner_page_size)):
                    pass


            if self.header.field_flags.value & 262144 != 0:
                pass
                for i in range(len(self.pivot)):
                    pass




    class ObjectBaseFrame(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ObjectBaseFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTextWrapper.ObjectBaseBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class ObjectHeader(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ObjectHeader, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.data_type = self._io.read_u2le()
            self.flex_offset = self._io.read_u4le()
            self.property_flags = SdocxTextWrapper.Bitfield(self._io, self, self._root)
            self.field_flags = SdocxTextWrapper.Bitfield(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            self.property_flags._fetch_instances()
            self.field_flags._fetch_instances()


    class OpaqueBody(KaitaiStruct):
        def __init__(self, expected_type, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.OpaqueBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.expected_type = expected_type
            self._read()

        def _read(self):
            self.header = SdocxTextWrapper.ObjectHeader(self._io, self, self._root)
            self.fixed_and_flex = self._io.read_bytes(self._io.size() - self._io.pos())


        def _fetch_instances(self):
            pass
            self.header._fetch_instances()


    class OpaqueFrame(KaitaiStruct):
        def __init__(self, expected_type, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.OpaqueFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.expected_type = expected_type
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTextWrapper.OpaqueBody(self.expected_type, _io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class OpaqueInlineBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.OpaqueInlineBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.raw = self._io.read_bytes_full()


        def _fetch_instances(self):
            pass


    class ParagraphRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ParagraphRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u2le()
            self.paragraph_type = self._io.read_u4le()
            self.start = self._io.read_u4le()
            self.end = self._io.read_u4le()
            self.extra = self._io.read_bytes(self.size - 12)


        def _fetch_instances(self):
            pass


    class Point(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.Point, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.x = self._io.read_f8le()
            self.y = self._io.read_f8le()


        def _fetch_instances(self):
            pass


    class SectionPair(KaitaiStruct):
        """A character range in Common.text. Non-empty body sections form a
        contiguous sequence: `text_start + text_length` equals the next range's
        `text_start` corpus-wide. Empty bodies use the special pair
        `(0xffffffff, 1)` followed by `(0, 0)`.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.SectionPair, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.text_start = self._io.read_u4le()
            self.text_length = self._io.read_u4le()


        def _fetch_instances(self):
            pass


    class ShapeBody(KaitaiStruct):
        def __init__(self, format_version, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ShapeBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.format_version = format_version
            self._read()

        def _read(self):
            self.header = SdocxTextWrapper.ObjectHeader(self._io, self, self._root)
            self.shape_type = self._io.read_u4le()
            self.original_rect = []
            for i in range(4):
                self.original_rect.append(self._io.read_f8le())

            self.original_angle = self._io.read_f4le()
            self.path_size = self._io.read_u4le()
            self.path = self._io.read_bytes(self.path_size)
            self.control_point_count = self._io.read_u1()
            self.control_points = []
            for i in range(self.control_point_count):
                self.control_points.append(SdocxTextWrapper.Point(self._io, self, self._root))

            if self.header.field_flags.value & 1 != 0:
                pass
                self.common_size = self._io.read_u4le()

            if self.header.field_flags.value & 1 != 0:
                pass
                self._raw_common = self._io.read_bytes(self.common_size)
                _io__raw_common = KaitaiStream(BytesIO(self._raw_common))
                self.common = SdocxTextWrapper.CommonFrame(_io__raw_common, self, self._root)

            if self.header.field_flags.value & 2048 != 0:
                pass
                self.shape_field_11_f32 = self._io.read_f4le()

            if self.header.field_flags.value & 4096 != 0:
                pass
                self.ellipsis_type = self._io.read_u1()

            if self.header.field_flags.value & 8192 != 0:
                pass
                self.text_auto_fit_type = self._io.read_u1()



        def _fetch_instances(self):
            pass
            self.header._fetch_instances()
            for i in range(len(self.original_rect)):
                pass

            for i in range(len(self.control_points)):
                pass
                self.control_points[i]._fetch_instances()

            if self.header.field_flags.value & 1 != 0:
                pass

            if self.header.field_flags.value & 1 != 0:
                pass
                self.common._fetch_instances()

            if self.header.field_flags.value & 2048 != 0:
                pass

            if self.header.field_flags.value & 4096 != 0:
                pass

            if self.header.field_flags.value & 8192 != 0:
                pass



    class ShapeFrame(KaitaiStruct):
        def __init__(self, format_version, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.ShapeFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self.format_version = format_version
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTextWrapper.ShapeBody(self.format_version, _io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class SpanRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.SpanRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u2le()
            self.span_type = self._io.read_u4le()
            self.start = self._io.read_u4le()
            self.end = self._io.read_u4le()
            self.interval_type = self._io.read_u4le()
            self.extra = self._io.read_bytes(self.size - 16)


        def _fetch_instances(self):
            pass

        @property
        def strikethrough_enabled(self):
            """Type-20 boolean stored in payload byte 0; remaining bytes are residue."""
            if hasattr(self, '_m_strikethrough_enabled'):
                return self._m_strikethrough_enabled

            if self.span_type == 20:
                pass
                self._m_strikethrough_enabled = KaitaiStream.byte_array_index(self.extra, 0)

            return getattr(self, '_m_strikethrough_enabled', None)


    class TextBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.TextBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.header = SdocxTextWrapper.ObjectHeader(self._io, self, self._root)
            if self.header.field_flags.value & 2 != 0:
                pass
                self.border_colour = self._io.read_bytes(4)

            if self.header.field_flags.value & 4 != 0:
                pass
                self.border_width = self._io.read_f4le()

            if self.header.field_flags.value & 8 != 0:
                pass
                self.border_type = self._io.read_u2le()



        def _fetch_instances(self):
            pass
            self.header._fetch_instances()
            if self.header.field_flags.value & 2 != 0:
                pass

            if self.header.field_flags.value & 4 != 0:
                pass

            if self.header.field_flags.value & 8 != 0:
                pass



    class TextFrame(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTextWrapper.TextFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTextWrapper.TextBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()



