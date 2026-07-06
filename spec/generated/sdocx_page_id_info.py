# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxPageIdInfo(KaitaiStruct):
    """The `pageIdInfo.dat` member of a `.sdocx` archive. It defines the true page
    order of the document (the `.page` members are named by UUID, not by order)
    and carries an opaque per-page hash.

    Layout is fully decoded with zero counterexamples across the 13-sample corpus:
    a 32-byte document head hash, a `u16` page count, then that many fixed 106-byte
    records. Every record is a 36-char UTF-16LE page UUID followed by a 32-byte
    per-page hash; the record is exactly filled (2 + 72 + 32 = 106), so there is no
    trailing padding.

    The per-page hash is stable manifest data but is NOT the SHA-256 of the raw
    `.page` member (0/48 matches on the corpus); its construction is Unknown and is
    documented as such in the companion Markdown rather than named here.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxPageIdInfo, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.head_hash = self._io.read_bytes(32)
        self.page_count = self._io.read_u2le()
        self.pages = []
        for i in range(self.page_count):
            self.pages.append(SdocxPageIdInfo.PageRecord(self._io, self, self._root))



    def _fetch_instances(self):
        pass
        for i in range(len(self.pages)):
            pass
            self.pages[i]._fetch_instances()


    class PageRecord(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPageIdInfo.PageRecord, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.uuid_len = self._io.read_u2le()
            self.uuid = (self._io.read_bytes(self.uuid_len * 2)).decode(u"UTF-16LE")
            self.page_hash = self._io.read_bytes(32)


        def _fetch_instances(self):
            pass



