# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxPage(KaitaiStruct):
    """The fixed header of a `.sdocx` archive's `<uuid>.page` member. Each page is one
    `.page` file; the header carries page dimensions, the page UUID, and the
    content bounding box, and is followed by a layer/object tree.
    
    Only the header is modeled here. The layer/object tree, the common object
    header (its `field_flags` additive size model), the non-stroke payload-geometry
    wrapper, and the stroke payloads (delta-compressed coordinates — procedural)
    are documented in the companion Markdown:
    
      - object tree + header  -> docs/format/container/page/object-header.md
      - payload geometry       -> docs/format/container/page/payload-geometry.md
      - strokes                -> docs/format/container/page/strokes.md
      - shapes/images/text     -> docs/format/container/page/object-types.md
    
    The `template` (grid/plain) is not a single fixed field — its offset depends on
    `base` and the note's source (built-in vs imported PDF) — so it is decoded
    procedurally and documented, not modeled here. The named fields below hold with
    zero counterexamples across the 13-sample corpus.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxPage, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.base = self._io.read_u4le()


    def _fetch_instances(self):
        pass
        _ = self.content_bbox
        if hasattr(self, '_m_content_bbox'):
            pass
            for i in range(len(self._m_content_bbox)):
                pass


        _ = self.footer_signature
        if hasattr(self, '_m_footer_signature'):
            pass

        _ = self.page_hash
        if hasattr(self, '_m_page_hash'):
            pass

        _ = self.page_height
        if hasattr(self, '_m_page_height'):
            pass

        _ = self.page_width
        if hasattr(self, '_m_page_width'):
            pass

        _ = self.uuid
        if hasattr(self, '_m_uuid'):
            pass

        _ = self.uuid_char_len
        if hasattr(self, '_m_uuid_char_len'):
            pass


    @property
    def content_bbox(self):
        """Content bounding box [x_min, y_min, x_max, y_max] as f64."""
        if hasattr(self, '_m_content_bbox'):
            return self._m_content_bbox

        _pos = self._io.pos()
        self._io.seek(128)
        self._m_content_bbox = []
        for i in range(4):
            self._m_content_bbox.append(self._io.read_f8le())

        self._io.seek(_pos)
        return getattr(self, '_m_content_bbox', None)

    @property
    def footer_signature(self):
        """Trailing marker; always "Page for SAMSUNG S-Pen SDK"."""
        if hasattr(self, '_m_footer_signature'):
            return self._m_footer_signature

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 26)
        self._m_footer_signature = (self._io.read_bytes(26)).decode(u"ASCII")
        self._io.seek(_pos)
        return getattr(self, '_m_footer_signature', None)

    @property
    def page_hash(self):
        """32-byte page content hash. This is exactly the value pageIdInfo.dat stores
        as the page's `page_hash` (the manifest copies it), which is why that
        manifest hash is not a digest of the raw .page member. Sits immediately
        before the footer signature.
        """
        if hasattr(self, '_m_page_hash'):
            return self._m_page_hash

        _pos = self._io.pos()
        self._io.seek(self._io.size() - 58)
        self._m_page_hash = self._io.read_bytes(32)
        self._io.seek(_pos)
        return getattr(self, '_m_page_hash', None)

    @property
    def page_height(self):
        """Page height in page units."""
        if hasattr(self, '_m_page_height'):
            return self._m_page_height

        _pos = self._io.pos()
        self._io.seek(26)
        self._m_page_height = self._io.read_u4le()
        self._io.seek(_pos)
        return getattr(self, '_m_page_height', None)

    @property
    def page_width(self):
        """Page width in page units."""
        if hasattr(self, '_m_page_width'):
            return self._m_page_width

        _pos = self._io.pos()
        self._io.seek(22)
        self._m_page_width = self._io.read_u4le()
        self._io.seek(_pos)
        return getattr(self, '_m_page_width', None)

    @property
    def uuid(self):
        """Page UUID; matches this member's filename and a pageIdInfo.dat record."""
        if hasattr(self, '_m_uuid'):
            return self._m_uuid

        _pos = self._io.pos()
        self._io.seek(40)
        self._m_uuid = (self._io.read_bytes(self.uuid_char_len * 2)).decode(u"UTF-16LE")
        self._io.seek(_pos)
        return getattr(self, '_m_uuid', None)

    @property
    def uuid_char_len(self):
        """UTF-16 character count of the page UUID."""
        if hasattr(self, '_m_uuid_char_len'):
            return self._m_uuid_char_len

        _pos = self._io.pos()
        self._io.seek(38)
        self._m_uuid_char_len = self._io.read_u2le()
        self._io.seek(_pos)
        return getattr(self, '_m_uuid_char_len', None)


