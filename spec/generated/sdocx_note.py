# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxNote(KaitaiStruct):
    """The leading metadata header of a `.sdocx` archive's `note.note` member. This
    header is deterministic and fully decoded (zero counterexamples across the
    13-sample corpus). It ends at the title object blob; everything after it —
    typed rich text, tables, and the tail records that begin at `offset_to_data` —
    is decoded procedurally (marker/TLV scanning, not a fixed layout) and is
    documented in the companion Markdown rather than modeled here:
    
      - typed rich text  -> docs/format/container/note-note/typed-text.md
      - tables           -> docs/format/container/note-note/tables.md
      - tail records     -> docs/format/container/note-note/tail-records.md
    
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



