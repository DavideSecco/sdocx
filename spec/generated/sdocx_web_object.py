# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxWebObject(KaitaiStruct):
    """Body of a type-13 object embedded in a text_core::Common inline-object
    vector. It consists of a generic ObjectBase inclusive frame followed by a
    type-13 inclusive flex frame. Field 7 is present in the sole corpus instance
    but its semantics are unknown, so it remains an opaque exclusive frame.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxWebObject, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.object_base_size = self._io.read_u4le()
        self.object_base_raw = self._io.read_bytes(self.object_base_size - 4)
        self.frame_size = self._io.read_u4le()
        self._raw_frame = self._io.read_bytes(self.frame_size - 4)
        _io__raw_frame = KaitaiStream(BytesIO(self._raw_frame))
        self.frame = SdocxWebObject.WebFrame(_io__raw_frame, self, self._root)


    def _fetch_instances(self):
        pass
        self.frame._fetch_instances()

    class OpaqueExclusive(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxWebObject.OpaqueExclusive, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.byte_size = self._io.read_u4le()
            self.raw = self._io.read_bytes(self.byte_size)


        def _fetch_instances(self):
            pass


    class ShortUtf16(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxWebObject.ShortUtf16, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class VarBitfield(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxWebObject.VarBitfield, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.len = self._io.read_u1()
            self.raw = self._io.read_bytes(self.len)


        def _fetch_instances(self):
            pass

        @property
        def value(self):
            if hasattr(self, '_m_value'):
                return self._m_value

            self._m_value = (((KaitaiStream.byte_array_index(self.raw, 0) if self.len >= 1 else 0) | (KaitaiStream.byte_array_index(self.raw, 1) << 8 if self.len >= 2 else 0)) | (KaitaiStream.byte_array_index(self.raw, 2) << 16 if self.len >= 3 else 0)) | (KaitaiStream.byte_array_index(self.raw, 3) << 24 if self.len >= 4 else 0)
            return getattr(self, '_m_value', None)


    class WebFrame(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxWebObject.WebFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.object_type = self._io.read_u2le()
            if not self.object_type == 13:
                raise kaitaistruct.ValidationNotEqualError(13, self.object_type, self._io, u"/types/web_frame/seq/0")
            self.flex_offset = self._io.read_u4le()
            self.property_flags = SdocxWebObject.VarBitfield(self._io, self, self._root)
            self.field_flags = SdocxWebObject.VarBitfield(self._io, self, self._root)
            if self.field_flags.value & 1 != 0:
                pass
                self.attached_html_file_id = self._io.read_u4le()

            if self.field_flags.value & 2 != 0:
                pass
                self.thumbnail_file_id = self._io.read_u4le()

            if self.field_flags.value & 4 != 0:
                pass
                self.body = SdocxWebObject.ShortUtf16(self._io, self, self._root)

            if self.field_flags.value & 8 != 0:
                pass
                self.title = SdocxWebObject.ShortUtf16(self._io, self, self._root)

            if self.field_flags.value & 16 != 0:
                pass
                self.uri = SdocxWebObject.ShortUtf16(self._io, self, self._root)

            self.image_type_id = self._io.read_u4le()
            if self.field_flags.value & 32 != 0:
                pass
                self.version = self._io.read_u4le()

            if self.field_flags.value & 64 != 0:
                pass
                self.view_type = self._io.read_u4le()

            if self.field_flags.value & 128 != 0:
                pass
                self.field_7_opaque = SdocxWebObject.OpaqueExclusive(self._io, self, self._root)



        def _fetch_instances(self):
            pass
            self.property_flags._fetch_instances()
            self.field_flags._fetch_instances()
            if self.field_flags.value & 1 != 0:
                pass

            if self.field_flags.value & 2 != 0:
                pass

            if self.field_flags.value & 4 != 0:
                pass
                self.body._fetch_instances()

            if self.field_flags.value & 8 != 0:
                pass
                self.title._fetch_instances()

            if self.field_flags.value & 16 != 0:
                pass
                self.uri._fetch_instances()

            if self.field_flags.value & 32 != 0:
                pass

            if self.field_flags.value & 64 != 0:
                pass

            if self.field_flags.value & 128 != 0:
                pass
                self.field_7_opaque._fetch_instances()


        @property
        def flex_offset_matches(self):
            if hasattr(self, '_m_flex_offset_matches'):
                return self._m_flex_offset_matches

            self._m_flex_offset_matches = self.flex_offset == (12 + self.property_flags.len) + self.field_flags.len
            return getattr(self, '_m_flex_offset_matches', None)

        @property
        def has_unhandled_field_flags(self):
            if hasattr(self, '_m_has_unhandled_field_flags'):
                return self._m_has_unhandled_field_flags

            self._m_has_unhandled_field_flags = self.field_flags.value & 4294967040 != 0
            return getattr(self, '_m_has_unhandled_field_flags', None)


    @property
    def consumes_eof(self):
        if hasattr(self, '_m_consumes_eof'):
            return self._m_consumes_eof

        self._m_consumes_eof = self._io.pos() == self._io.size()
        return getattr(self, '_m_consumes_eof', None)


