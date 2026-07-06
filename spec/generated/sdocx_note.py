# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxNote(KaitaiStruct):
    """The leading metadata header of a `.sdocx` archive's `note.note` member. This
    header is deterministic and fully decoded (zero counterexamples across the
    13-sample corpus). It ends at the title object blob; most content after it —
    typed rich text, tables, and marker-located tail records — is decoded
    procedurally (marker/TLV scanning, not a fixed layout) and is documented in
    the companion Markdown rather than forced into Kaitai:

      - typed rich text  -> docs/format/container/note-note/typed-text.md
      - tables           -> docs/format/container/note-note/tables.md
      - tail records     -> docs/format/container/note-note/tail-records.md

    Only fixed-boundary tail anchors are modeled as instances: the sentinel at
    `offset_to_data`, the trailing 32-byte note hash copied into pageIdInfo.dat,
    and the two EOF-relative tail-hash-block candidate windows seen in the corpus
    (EOF-aligned, or followed by a 4-byte post-hash u32). Marker-scanned pen and
    voice records remain procedural.

    Note the two single-byte pads after `offset_to_data` and after `flags`; they
    are part of the on-disk layout, not alignment we add.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxNote, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.offset_to_data = self._io.read_s4le()
        self.reserved_at_4 = self._io.read_bytes(1)
        self.flags = self._io.read_s4le()
        self.reserved_at_9 = self._io.read_bytes(1)
        self.meta_flags = self._io.read_s4le()
        self.format_version = self._io.read_s4le()
        self.note_id = SdocxNote.ShortUtf16(self._io, self, self._root)
        self.file_revision = self._io.read_s4le()
        self.created_time = self._io.read_s8le()
        self.modified_time = self._io.read_s8le()
        self.width = self._io.read_s4le()
        self.height = self._io.read_s4le()
        self.page_h_padding = self._io.read_s4le()
        self.page_v_padding = self._io.read_s4le()
        self.min_format_version = self._io.read_s4le()
        self.title_size = self._io.read_s4le()
        self.title_blob = self._io.read_bytes((self.title_size if self.title_size > 0 else 0))


    def _fetch_instances(self):
        pass
        self.note_id._fetch_instances()
        _ = self.tail_hash_block_before_post_u32
        if hasattr(self, '_m_tail_hash_block_before_post_u32'):
            pass
            self._m_tail_hash_block_before_post_u32._fetch_instances()

        _ = self.tail_hash_block_eof
        if hasattr(self, '_m_tail_hash_block_eof'):
            pass
            self._m_tail_hash_block_eof._fetch_instances()

        _ = self.tail_sentinel
        if hasattr(self, '_m_tail_sentinel'):
            pass

        _ = self.trailing_hash
        if hasattr(self, '_m_trailing_hash'):
            pass


    class ShortUtf16(KaitaiStruct):
        """A u16 character count followed by that many UTF-16LE code units."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.ShortUtf16, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_s2le()
            self.value = (self._io.read_bytes((self.char_len * 2 if self.char_len > 0 else 0))).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class TailHashBlock(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.TailHashBlock, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.prefix_u32 = []
            for i in range(2):
                self.prefix_u32.append(self._io.read_u4le())

            self.hash32 = self._io.read_bytes(32)


        def _fetch_instances(self):
            pass
            for i in range(len(self.prefix_u32)):
                pass



    @property
    def tail_hash_block_before_post_u32(self):
        """Candidate 40-byte tail hash block when followed by a 4-byte post-hash u32."""
        if hasattr(self, '_m_tail_hash_block_before_post_u32'):
            return self._m_tail_hash_block_before_post_u32

        if self._io.size() >= 44:
            pass
            _pos = self._io.pos()
            self._io.seek(self._io.size() - 44)
            self._m_tail_hash_block_before_post_u32 = SdocxNote.TailHashBlock(self._io, self, self._root)
            self._io.seek(_pos)

        return getattr(self, '_m_tail_hash_block_before_post_u32', None)

    @property
    def tail_hash_block_eof(self):
        """Candidate 40-byte tail hash block when the block ends at EOF."""
        if hasattr(self, '_m_tail_hash_block_eof'):
            return self._m_tail_hash_block_eof

        if self._io.size() >= 40:
            pass
            _pos = self._io.pos()
            self._io.seek(self._io.size() - 40)
            self._m_tail_hash_block_eof = SdocxNote.TailHashBlock(self._io, self, self._root)
            self._io.seek(_pos)

        return getattr(self, '_m_tail_hash_block_eof', None)

    @property
    def tail_sentinel(self):
        """Fixed 16-byte tail sentinel at `offset_to_data`."""
        if hasattr(self, '_m_tail_sentinel'):
            return self._m_tail_sentinel

        _pos = self._io.pos()
        self._io.seek(self.offset_to_data)
        self._m_tail_sentinel = self._io.read_bytes(16)
        self._io.seek(_pos)
        return getattr(self, '_m_tail_sentinel', None)

    @property
    def trailing_hash(self):
        """The note's trailing hash; exactly pageIdInfo.dat `head_hash`."""
        if hasattr(self, '_m_trailing_hash'):
            return self._m_trailing_hash

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 32)
        self._m_trailing_hash = self._io.read_bytes(32)
        self._io.seek(_pos)
        return getattr(self, '_m_trailing_hash', None)


