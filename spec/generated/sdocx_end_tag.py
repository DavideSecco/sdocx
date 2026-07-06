# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxEndTag(KaitaiStruct):
    """The `end_tag.bin` member of a Samsung Notes `.sdocx` archive: a fixed-shape
    footer record that closes the document. Two size families are seen in the
    corpus: a 148-byte footer (payload_size = 146) on newer notes, and a
    144-byte footer (payload_size = 142) on `handwritten.sdocx`.

    Only the byte ranges named below are decoded with zero counterexamples across
    the 13-sample corpus. The gaps between them (documented as `*_raw` islands in
    the companion Markdown) are structurally bounded but not yet semantically
    named, so they are deliberately left unmodeled here rather than given
    speculative field names. The trailing footer constants and the ASCII
    signature are located from the end of the stream so both size families parse
    with one definition.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxEndTag, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.payload_size = self._io.read_u2le()
        self.format_version = self._io.read_u2le()
        self.reserved_at_4 = self._io.read_u4le()
        self.modified_time = self._io.read_s8le()


    def _fetch_instances(self):
        pass
        _ = self.created_time_a
        if hasattr(self, '_m_created_time_a'):
            pass

        _ = self.created_time_b
        if hasattr(self, '_m_created_time_b'):
            pass

        _ = self.created_time_header
        if hasattr(self, '_m_created_time_header'):
            pass

        _ = self.document_height
        if hasattr(self, '_m_document_height'):
            pass

        _ = self.extra_time_candidate
        if hasattr(self, '_m_extra_time_candidate'):
            pass

        _ = self.format_version_dup
        if hasattr(self, '_m_format_version_dup'):
            pass

        _ = self.page_width
        if hasattr(self, '_m_page_width'):
            pass

        _ = self.signature
        if hasattr(self, '_m_signature'):
            pass


    @property
    def created_time_a(self):
        """Creation-time candidate. Exact note created_time on the 10 newer samples;
        a millisecond-close value on the 3 older imported samples.
        """
        if hasattr(self, '_m_created_time_a'):
            return self._m_created_time_a

        _pos = self._io.pos()
        self._io.seek(72)
        self._m_created_time_a = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_created_time_a', None)

    @property
    def created_time_b(self):
        """Second creation-time candidate; identical to created_time_a on the 10
        newer samples, a different ms-like time on the older imports.
        """
        if hasattr(self, '_m_created_time_b'):
            return self._m_created_time_b

        _pos = self._io.pos()
        self._io.seek(80)
        self._m_created_time_b = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_created_time_b', None)

    @property
    def created_time_header(self):
        """Creation-time candidate carried in the header region."""
        if hasattr(self, '_m_created_time_header'):
            return self._m_created_time_header

        _pos = self._io.pos()
        self._io.seek(46)
        self._m_created_time_header = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_created_time_header', None)

    @property
    def document_height(self):
        """Document/note height; equals note.note height on the current corpus."""
        if hasattr(self, '_m_document_height'):
            return self._m_document_height

        _pos = self._io.pos()
        self._io.seek(26)
        self._m_document_height = self._io.read_f4le()
        self._io.seek(_pos)
        return getattr(self, '_m_document_height', None)

    @property
    def extra_time_candidate(self):
        """Additional timestamp-like value; non-zero on only 2 samples."""
        if hasattr(self, '_m_extra_time_candidate'):
            return self._m_extra_time_candidate

        _pos = self._io.pos()
        self._io.seek(88)
        self._m_extra_time_candidate = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_extra_time_candidate', None)

    @property
    def format_version_dup(self):
        """Duplicate of format_version; equal to it on every sample."""
        if hasattr(self, '_m_format_version_dup'):
            return self._m_format_version_dup

        _pos = self._io.pos()
        self._io.seek(42)
        self._m_format_version_dup = self._io.read_u2le()
        self._io.seek(_pos)
        return getattr(self, '_m_format_version_dup', None)

    @property
    def page_width(self):
        """Page width; equals the page header width on the current corpus."""
        if hasattr(self, '_m_page_width'):
            return self._m_page_width

        _pos = self._io.pos()
        self._io.seek(22)
        self._m_page_width = self._io.read_u2le()
        self._io.seek(_pos)
        return getattr(self, '_m_page_width', None)

    @property
    def signature(self):
        """Trailing ASCII marker; always "Document for S-Pen SDK"."""
        if hasattr(self, '_m_signature'):
            return self._m_signature

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 22)
        self._m_signature = (self._io.read_bytes(22)).decode(u"ASCII")
        self._io.seek(_pos)
        return getattr(self, '_m_signature', None)


