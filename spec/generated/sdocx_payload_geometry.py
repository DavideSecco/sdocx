# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxPayloadGeometry(KaitaiStruct):
    """The geometry wrapper that begins the payload of a non-stroke inserted object
    (shape, image, in-page text box), immediately after the common object header
    (i.e. at object-blob offset `total_size`). Fed that payload slice.
    
    Decoded corpus-wide: 412/412 wrapper-bearing objects (shape 390, image 15,
    text_box 7). Only the wrapper header + coordinate points are modeled here; the
    later semantic markers (shape/image/text) and per-shape point roles are marker-
    scanned and documented in docs/format/container/page/payload-geometry.md.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxPayloadGeometry, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.l0 = self._io.read_u4le()
        self.tag = self._io.read_u2le()
        self.l1 = self._io.read_u4le()
        self.opcode = self._io.read_bytes(4)
        self.point_count = self._io.read_u4le()
        self.points = []
        for i in range(self.point_count):
            self.points.append(SdocxPayloadGeometry.Point(self._io, self, self._root))



    def _fetch_instances(self):
        pass
        for i in range(len(self.points)):
            pass
            self.points[i]._fetch_instances()


    class Point(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPayloadGeometry.Point, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.x = self._io.read_f8le()
            self.y = self._io.read_f8le()


        def _fetch_instances(self):
            pass



