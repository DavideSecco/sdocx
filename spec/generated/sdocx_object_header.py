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
    ADDITIVE `field_flags` size model (zero counterexamples across the corpus):

      0x1     ANGLE      +4   rotation-angle f32 at offset 105
      0x20    EXTRA_KEY  +32  "extra_key_stroke_shape" attribute block
      0x40000 HDR_EXT    +16  [counter, seq, page_width, page_height]
      0x8000  MEDIA_FAMILY  0 image/shape/drawing discriminator (no size)
      0x2000|0x4000 BASE   0  present on every object

    The three size-contributing blocks are stored in bit order (angle, then
    extra_key, then hdr_ext), so this type reads them in that order. Payload data
    after the header (strokes, geometry wrappers) is NOT read here.

    Corpus invariants baked in: `flag_len == 2` and `field_len == 4` on all 11788
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
            self.extra_key = SdocxObjectHeader.ExtraKeyBlock(self._io, self, self._root)

        if self.field_flags & 262144 != 0:
            pass
            self.hdr_ext = SdocxObjectHeader.HeaderExt(self._io, self, self._root)



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


    class ExtraKeyBlock(KaitaiStruct):
        """32-byte named attribute block; identical on 40/40 objects that set 0x20."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxObjectHeader.ExtraKeyBlock, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.head = self._io.read_bytes(3)
            self.key_len = self._io.read_u2le()
            self.key = (self._io.read_bytes(self.key_len)).decode(u"ASCII")
            self.trailing = self._io.read_u4le()


        def _fetch_instances(self):
            pass


    class HeaderExt(KaitaiStruct):
        """16-byte extension; page_width/height match the page header 1690/1690."""
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



