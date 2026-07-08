# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxEndTag(KaitaiStruct):
    """The `end_tag.bin` member of a Samsung Notes `.sdocx` archive: a sequential
    S Pen SDK document footer. The field names are independently cross-checked
    against `sdocx2pdf` and validated on the 13-sample corpus. Two size families
    are seen: a 148-byte footer (payload_size = 146) on newer notes, and a
    144-byte footer (payload_size = 142) on `handwritten.sdocx`; the shorter
    legacy footer omits the zero-length `app_custom_data` field before the
    signature.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxEndTag, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.payload_size = self._io.read_u2le()
        self.format_version = self._io.read_u4le()
        self.note_uuid_len = self._io.read_u2le()
        self.note_uuid = (self._io.read_bytes(self.note_uuid_len * 2)).decode(u"UTF-16LE")
        self.modified_time = self._io.read_s8le()
        self.property_flags = self._io.read_u4le()
        self.cover_image_len = self._io.read_u2le()
        self.cover_image = (self._io.read_bytes(self.cover_image_len * 2)).decode(u"UTF-16LE")
        self.note_width = self._io.read_u4le()
        self.document_height = self._io.read_f4le()
        self.app_name_len = self._io.read_u2le()
        self.app_name = (self._io.read_bytes(self.app_name_len * 2)).decode(u"UTF-16LE")
        self.app_version_major = self._io.read_u4le()
        self.app_version_minor = self._io.read_u4le()
        self.app_version_patch_name_len = self._io.read_u2le()
        self.app_version_patch_name = (self._io.read_bytes(self.app_version_patch_name_len * 2)).decode(u"UTF-16LE")
        self.min_format_version = self._io.read_u4le()
        self.created_time_header = self._io.read_s8le()
        self.last_viewed_page_index = self._io.read_u4le()
        self.page_model = self._io.read_u2le()
        self.document_type = self._io.read_u2le()
        self.owner_id_len = self._io.read_u2le()
        self.owner_id = (self._io.read_bytes(self.owner_id_len * 2)).decode(u"UTF-16LE")
        self.skipped_size = self._io.read_u4le()
        self.skipped_data = self._io.read_bytes(self.skipped_size)
        self.encryption_data_size = self._io.read_u4le()
        self.encryption_data = self._io.read_bytes(self.encryption_data_size)
        self.display_created_time = self._io.read_s8le()
        self.display_modified_time = self._io.read_s8le()
        self.last_recognised_data_modified_time = self._io.read_s8le()
        self.fixed_font_len = self._io.read_u2le()
        self.fixed_font = (self._io.read_bytes(self.fixed_font_len * 2)).decode(u"UTF-16LE")
        self.fixed_text_direction = self._io.read_u4le()
        self.fixed_background_theme = self._io.read_u4le()
        self.server_checkpoint = self._io.read_s8le()
        self.new_orientation = self._io.read_u4le()
        self.min_unknown_version = self._io.read_u4le()
        if self._io.pos() < self._io.size() - 22:
            pass
            self.app_custom_data_len = self._io.read_u4le()

        if self._io.pos() < self._io.size() - 22:
            pass
            self.app_custom_data = (self._io.read_bytes(self.app_custom_data_len * 2)).decode(u"UTF-16LE")



    def _fetch_instances(self):
        pass
        if self._io.pos() < self._io.size() - 22:
            pass

        if self._io.pos() < self._io.size() - 22:
            pass

        _ = self.created_time_a
        if hasattr(self, '_m_created_time_a'):
            pass

        _ = self.created_time_b
        if hasattr(self, '_m_created_time_b'):
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
        """Back-compat alias for display_created_time."""
        if hasattr(self, '_m_created_time_a'):
            return self._m_created_time_a

        _pos = self._io.pos()
        self._io.seek(72)
        self._m_created_time_a = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_created_time_a', None)

    @property
    def created_time_b(self):
        """Back-compat alias for display_modified_time."""
        if hasattr(self, '_m_created_time_b'):
            return self._m_created_time_b

        _pos = self._io.pos()
        self._io.seek(80)
        self._m_created_time_b = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_created_time_b', None)

    @property
    def extra_time_candidate(self):
        """Back-compat alias for last_recognised_data_modified_time."""
        if hasattr(self, '_m_extra_time_candidate'):
            return self._m_extra_time_candidate

        _pos = self._io.pos()
        self._io.seek(88)
        self._m_extra_time_candidate = self._io.read_s8le()
        self._io.seek(_pos)
        return getattr(self, '_m_extra_time_candidate', None)

    @property
    def format_version_dup(self):
        """Back-compat alias for min_format_version."""
        if hasattr(self, '_m_format_version_dup'):
            return self._m_format_version_dup

        _pos = self._io.pos()
        self._io.seek(42)
        self._m_format_version_dup = self._io.read_u4le()
        self._io.seek(_pos)
        return getattr(self, '_m_format_version_dup', None)

    @property
    def page_width(self):
        """Low 16 bits of note_width; equals the page header width on the current corpus."""
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


