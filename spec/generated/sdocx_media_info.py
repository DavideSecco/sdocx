# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxMediaInfo(KaitaiStruct):
    """The `media/mediaInfo.dat` manifest inside a `.sdocx` archive: one record per
    attachment under `media/`, closed by the ASCII trailer `EOFX`.

    Fully decoded with zero counterexamples across the 13-sample corpus: a `u32`
    magic, a `u16` record count, then that many length-prefixed records. Each
    record's `payload_size` counts the bytes after itself and frames a body of
    `[u32 media_index][u16 name_chars][UTF-16LE filename][64-byte ASCII SHA-256
    hex][raw tail]`. The filename already includes the `<index>@...` prefix used
    under `media/`. On the corpus, 60/60 records point at existing archive members
    and every SHA-256 verifies.

    The record's 11-byte tail is structurally modeled as
    `[u16 tag][u64 time_candidate][u8 marker]`. The boundaries are decoded with
    zero counterexamples; the tag/time semantics remain deliberately conservative
    (see the companion Markdown).
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxMediaInfo, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.magic = self._io.read_u4le()
        self.record_count = self._io.read_u2le()
        self.records = []
        for i in range(self.record_count):
            self.records.append(SdocxMediaInfo.MediaRecord(self._io, self, self._root))

        self.eof = (self._io.read_bytes(4)).decode(u"ASCII")


    def _fetch_instances(self):
        pass
        for i in range(len(self.records)):
            pass
            self.records[i]._fetch_instances()


    class MediaBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxMediaInfo.MediaBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.media_index = self._io.read_u4le()
            self.name_len = self._io.read_u2le()
            self.name = (self._io.read_bytes(self.name_len * 2)).decode(u"UTF-16LE")
            self.sha256 = (self._io.read_bytes(64)).decode(u"ASCII")
            self._raw_tail = self._io.read_bytes_full()
            _io__raw_tail = KaitaiStream(BytesIO(self._raw_tail))
            self.tail = SdocxMediaInfo.MediaTail(_io__raw_tail, self, self._root)


        def _fetch_instances(self):
            pass
            self.tail._fetch_instances()


    class MediaRecord(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxMediaInfo.MediaRecord, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.payload_size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.payload_size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxMediaInfo.MediaBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class MediaTail(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxMediaInfo.MediaTail, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.tag = self._io.read_u2le()
            self.time_candidate = self._io.read_u8le()
            self.marker = self._io.read_u1()


        def _fetch_instances(self):
            pass



