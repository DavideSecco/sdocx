# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
import sdocx_object_header


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxPage(KaitaiStruct):
    """A `.sdocx` archive's `<uuid>.page` member. Each page is one `.page` file; the
    header carries page dimensions, the page UUID, and the content bounding box,
    and is followed by a layer/object tree.

    The layer/object tree is structural: object entries carry raw type, child
    count, and blob size, and recursive children follow the blob. The blob itself
    begins with the common object header, modeled by `sdocx_object_header` via a
    substream. Payload internals (strokes, semantic shape/image/text markers) stay
    procedural and are documented in the companion Markdown:

      - layer/object tree     -> docs/format/container/page/README.md
      - common object header  -> docs/format/container/page/object-header.md
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

        _ = self.tree
        if hasattr(self, '_m_tree'):
            pass
            self._m_tree._fetch_instances()

        _ = self.uuid
        if hasattr(self, '_m_uuid'):
            pass

        _ = self.uuid_char_len
        if hasattr(self, '_m_uuid_char_len'):
            pass


    class Layer(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.Layer, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.layer_prefix = self._io.read_u4le()
            self.next_offset = self._io.read_u4le()
            self.flag1 = self._io.read_u1()
            self.flag2 = self._io.read_u1()
            self.flag3 = self._io.read_u1()
            self.content_flags = self._io.read_u1()
            self.layer_flags = self._io.read_u4le()
            if self.content_flags & 1 != 0:
                pass
                self.content_01 = self._io.read_u1()

            if self.content_flags & 2 != 0:
                pass
                self.content_02 = self._io.read_bytes(4)

            if self.content_flags & 4 != 0:
                pass
                self.content_04_text = SdocxPage.Utf16String(self._io, self, self._root)

            if self.content_flags & 8 != 0:
                pass
                self.layer_uuid = SdocxPage.Utf16String(self._io, self, self._root)

            if self.content_flags & 16 != 0:
                pass
                self.modified_time = self._io.read_s8le()

            if self.content_flags & 32 != 0:
                pass
                self.content_20 = self._io.read_bytes(4)

            self.object_count = self._io.read_u4le()
            self.objects = []
            for i in range(self.object_count):
                self.objects.append(SdocxPage.ObjectEntry(self._io, self, self._root))

            self.layer_hash = self._io.read_bytes(32)


        def _fetch_instances(self):
            pass
            if self.content_flags & 1 != 0:
                pass

            if self.content_flags & 2 != 0:
                pass

            if self.content_flags & 4 != 0:
                pass
                self.content_04_text._fetch_instances()

            if self.content_flags & 8 != 0:
                pass
                self.layer_uuid._fetch_instances()

            if self.content_flags & 16 != 0:
                pass

            if self.content_flags & 32 != 0:
                pass

            for i in range(len(self.objects)):
                pass
                self.objects[i]._fetch_instances()



    class ObjectEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.ObjectEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.raw_type = self._io.read_u1()
            self.child_count = self._io.read_s2le()
            self.blob_size = self._io.read_u4le()
            self._raw_blob = self._io.read_bytes(self.blob_size)
            _io__raw_blob = KaitaiStream(BytesIO(self._raw_blob))
            self.blob = sdocx_object_header.SdocxObjectHeader(_io__raw_blob)
            self.children = []
            for i in range((self.child_count if self.child_count > 0 else 0)):
                self.children.append(SdocxPage.ObjectEntry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            self.blob._fetch_instances()
            for i in range(len(self.children)):
                pass
                self.children[i]._fetch_instances()



    class PageTree(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.PageTree, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.layer_count = self._io.read_u2le()
            self.current_layer_index = self._io.read_u2le()
            self.layers = []
            for i in range(self.layer_count):
                self.layers.append(SdocxPage.Layer(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.layers)):
                pass
                self.layers[i]._fetch_instances()


        @property
        def has_objects(self):
            """Current corpus has one layer; its declared object count gates the preamble content_bbox."""
            if hasattr(self, '_m_has_objects'):
                return self._m_has_objects

            self._m_has_objects = (len(self.layers) > 0) and (self.layers[0].object_count > 0)
            return getattr(self, '_m_has_objects', None)


    class Utf16String(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxPage.Utf16String, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    @property
    def content_bbox(self):
        """Optional content bounding box [x_min, y_min, x_max, y_max] as f64; present iff the layer tree declares objects."""
        if hasattr(self, '_m_content_bbox'):
            return self._m_content_bbox

        if self.tree.has_objects:
            pass
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
    def tree(self):
        """Layer/object tree rooted at the header's `base` offset."""
        if hasattr(self, '_m_tree'):
            return self._m_tree

        _pos = self._io.pos()
        self._io.seek(self.base)
        self._m_tree = SdocxPage.PageTree(self._io, self, self._root)
        self._io.seek(_pos)
        return getattr(self, '_m_tree', None)

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

