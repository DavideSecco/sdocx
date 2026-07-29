# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxObjectHeader(KaitaiStruct):
    """The common header at the start of every object in a `.page` layer/object tree.
    Fed one object blob (the bytes from an object entry's stored size). The base
    header is a fixed layout ending at offset 105; its length then grows by an
    `field_flags`-gated extension model:

      0x1     ANGLE      +4   rotation-angle f32 at offset 105
      0x20    EXTRA_BUNDLE generic ObjectBase property bag
      0x40000 HDR_EXT    +16  [counter, seq, page_width, page_height]
      0x8000  MEDIA_FAMILY  0 image/shape/drawing discriminator (no size)
      0x2000|0x4000 BASE   0  present on every object

    The extensions are stored in bit order (angle, then extra_key, then hdr_ext).
    The extra-bundle block consumes the bytes up to the optional final 16-byte
    HDR_EXT. Payload data
    after the header (strokes, geometry wrappers) is NOT read here.

    Corpus invariants baked in: `flag_len == 2` and `field_len == 4` on all
    objects, and `uuid_len == 36`, which is what makes the base header land exactly
    at 105. A future variant that breaks these would surface as a test-gate
    mismatch against pysdocx.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxObjectHeader, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.total_size = self._io.read_u4le()
        self.data_type = self._io.read_s2le()
        self.var_data_offset = self._io.read_u4le()
        self.flag_len = self._io.read_u1()
        self.flags = self._io.read_u2le()
        self.field_len = self._io.read_u1()
        self.field_flags = self._io.read_u4le()
        self.format_version = self._io.read_u4le()
        self.uuid_len = self._io.read_s2le()
        self.uuid = (self._io.read_bytes(self.uuid_len)).decode(u"UTF-8")
        self.modified_time = self._io.read_s8le()
        self.bbox = []
        for i in range(4):
            self.bbox.append(self._io.read_f8le())

        self.timestamp = self._io.read_u4le()
        self.resizable = self._io.read_u1()
        if self.field_flags & 1 != 0:
            pass
            self.angle_deg = self._io.read_f4le()

        if self.field_flags & 32 != 0:
            pass
            self._raw_extra_key = self._io.read_bytes((((self.total_size - self._io.pos()) - (16 if self.field_flags & 262144 != 0 else 0)) - 16 if self.extra_key_head != 2 else 32))
            _io__raw_extra_key = KaitaiStream(BytesIO(self._raw_extra_key))
            self.extra_key = SdocxObjectHeader.ExtraKeyBlock(_io__raw_extra_key, self, self._root)

        if self.field_flags & 262144 != 0:
            pass
            self.hdr_ext = SdocxObjectHeader.HeaderExt(self._io, self, self._root)

        if  ((self.field_flags & 32 != 0) and (self.extra_key_head != 2)) :
            pass
            self.math_header_tail = self._io.read_bytes(16)



    def _fetch_instances(self):
        pass
        for i in range(len(self.bbox)):
            pass

        if self.field_flags & 1 != 0:
            pass

        if self.field_flags & 32 != 0:
            pass
            self.extra_key._fetch_instances()

        if self.field_flags & 262144 != 0:
            pass
            self.hdr_ext._fetch_instances()

        if  ((self.field_flags & 32 != 0) and (self.extra_key_head != 2)) :
            pass

        _ = self.extra_key_head
        if hasattr(self, '_m_extra_key_head'):
            pass


    class AsciiKey(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.AsciiKey, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.byte_count = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.byte_count)).decode(u"ASCII")


        def _fetch_instances(self):
            pass


    class ByteVecProperty(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.ByteVecProperty, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxObjectHeader.AsciiKey(self._io, self, self._root)
            self.byte_count = self._io.read_u4le()
            self.value = self._io.read_bytes(self.byte_count)


        def _fetch_instances(self):
            pass
            self.key._fetch_instances()


    class ExtraKeyBlock(KaitaiStruct):
        """Generic ObjectBase bundle/property bag (sdocx2pdf `Bundle`): a one-byte
        presence bitfield gates string, u32, string-vector and byte-buffer maps.
        Older notes called the first three bytes a `head`; in this model those
        bytes are simply `presence_flags + u16 map_count`.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.ExtraKeyBlock, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.presence_flags = self._io.read_u1()
            if self.presence_flags & 1 != 0:
                pass
                self.string_prop_count = self._io.read_u2le()

            if self.presence_flags & 1 != 0:
                pass
                self.string_props = []
                for i in range(self.string_prop_count):
                    self.string_props.append(SdocxObjectHeader.StringProperty(self._io, self, self._root))


            if self.presence_flags & 2 != 0:
                pass
                self.integer_prop_count = self._io.read_u2le()

            if self.presence_flags & 2 != 0:
                pass
                self.integer_props = []
                for i in range(self.integer_prop_count):
                    self.integer_props.append(SdocxObjectHeader.IntegerProperty(self._io, self, self._root))


            if self.presence_flags & 4 != 0:
                pass
                self.string_vec_prop_count = self._io.read_u2le()

            if self.presence_flags & 4 != 0:
                pass
                self.string_vec_props = []
                for i in range(self.string_vec_prop_count):
                    self.string_vec_props.append(SdocxObjectHeader.StringVecProperty(self._io, self, self._root))


            if self.presence_flags & 8 != 0:
                pass
                self.byte_vec_prop_count = self._io.read_u2le()

            if self.presence_flags & 8 != 0:
                pass
                self.byte_vec_props = []
                for i in range(self.byte_vec_prop_count):
                    self.byte_vec_props.append(SdocxObjectHeader.ByteVecProperty(self._io, self, self._root))




        def _fetch_instances(self):
            pass
            if self.presence_flags & 1 != 0:
                pass

            if self.presence_flags & 1 != 0:
                pass
                for i in range(len(self.string_props)):
                    pass
                    self.string_props[i]._fetch_instances()


            if self.presence_flags & 2 != 0:
                pass

            if self.presence_flags & 2 != 0:
                pass
                for i in range(len(self.integer_props)):
                    pass
                    self.integer_props[i]._fetch_instances()


            if self.presence_flags & 4 != 0:
                pass

            if self.presence_flags & 4 != 0:
                pass
                for i in range(len(self.string_vec_props)):
                    pass
                    self.string_vec_props[i]._fetch_instances()


            if self.presence_flags & 8 != 0:
                pass

            if self.presence_flags & 8 != 0:
                pass
                for i in range(len(self.byte_vec_props)):
                    pass
                    self.byte_vec_props[i]._fetch_instances()




    class HeaderExt(KaitaiStruct):
        """16-byte extension; page_width/height match every corpus page header."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.HeaderExt, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.counter = self._io.read_u4le()
            self.seq = self._io.read_u4le()
            self.page_width = self._io.read_u4le()
            self.page_height = self._io.read_u4le()


        def _fetch_instances(self):
            pass


    class IntegerProperty(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.IntegerProperty, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxObjectHeader.AsciiKey(self._io, self, self._root)
            self.value = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.key._fetch_instances()


    class NamedStringArrayProperty(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.NamedStringArrayProperty, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.separator = self._io.read_u2le()
            self.key_len = self._io.read_u2le()
            self.key = (self._io.read_bytes(self.key_len)).decode(u"ASCII")
            self.string_count = self._io.read_u2le()
            self.strings = []
            for i in range(self.string_count):
                self.strings.append(SdocxObjectHeader.Utf16String(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.strings)):
                pass
                self.strings[i]._fetch_instances()



    class NamedU32Property(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.NamedU32Property, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.separator = self._io.read_u2le()
            self.key_len = self._io.read_u2le()
            self.key = (self._io.read_bytes(self.key_len)).decode(u"ASCII")
            self.value = self._io.read_u4le()


        def _fetch_instances(self):
            pass


    class StringProperty(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.StringProperty, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxObjectHeader.AsciiKey(self._io, self, self._root)
            self.value = SdocxObjectHeader.Utf16String(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            self.key._fetch_instances()
            self.value._fetch_instances()


    class StringVecProperty(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.StringVecProperty, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.key = SdocxObjectHeader.AsciiKey(self._io, self, self._root)
            self.string_count = self._io.read_u2le()
            self.strings = []
            for i in range(self.string_count):
                self.strings.append(SdocxObjectHeader.Utf16String(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            self.key._fetch_instances()
            for i in range(len(self.strings)):
                pass
                self.strings[i]._fetch_instances()



    class Utf16String(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.Utf16String, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_count = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_count * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    @property
    def extra_key_head(self):
        if hasattr(self, '_m_extra_key_head'):
            return self._m_extra_key_head

        if self.field_flags & 32 != 0:
            pass
            _pos = self._io.pos()
            self._io.seek(105 + (4 if self.field_flags & 1 != 0 else 0))
            self._m_extra_key_head = self._io.read_u1()
            self._io.seek(_pos)

        return getattr(self, '_m_extra_key_head', None)


