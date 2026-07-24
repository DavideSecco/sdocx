# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
import sdocx_text_wrapper


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxNote(KaitaiStruct):
    """The whole `note.note` member of a `.sdocx` archive, parsed as one sequential
    structure (validated with zero counterexamples across the corpus by
    `spec/tools/validate_note.py` and `spec/tools/analyze_note_doc.py`).

    Layout: a fixed header (two variable-length bitfields, ids, timestamps in
    epoch MICROseconds, note geometry), the length-prefixed title and body Text
    blobs, an optional pre-flex gap, then a run of optional "flex" fields, each
    gated by one bit of `field_flags`, and finally the trailing 32-byte
    `sha256(note.note[:-32])` digest (the same digest copied into
    `pageIdInfo.dat.head_hash`). The parse consuming bytes `0 .. size-32`
    exactly is the structural gate: every intermediate boundary must be correct
    for `trailing_hash` to land on the real hash.

    The title/body blobs are Text objects parsed through the imported
    `sdocx_text_wrapper` inheritance chain; Shape's flex offset lands on their
    `text_core::Common` rich-text frame without scanning (see
    docs/format/container/note-note/typed-text.md). Everything else that was
    previously marker-scanned in the tail (pen preload paths, pen style tails,
    voice clips, the string registry pairing each pen with its parameter
    string) is now these flex fields.

    Field names cross-referenced from squ1dd13/sdocx2pdf (MIT), re-validated
    field-by-field on the local corpus. Old pysdocx aliases: `flex_offset` was
    `offset_to_data`, `property_flags` was `flags`, `field_flags` was
    `meta_flags`.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxNote, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.flex_offset = self._io.read_u4le()
        self.property_flags = SdocxNote.VarBitfield(self._io, self, self._root)
        self.field_flags = SdocxNote.VarBitfield(self._io, self, self._root)
        self.format_version = self._io.read_u4le()
        self.note_id = SdocxNote.ShortUtf16(self._io, self, self._root)
        self.file_revision = self._io.read_u4le()
        self.created_time_us = self._io.read_s8le()
        self.modified_time_us = self._io.read_s8le()
        self.width = self._io.read_u4le()
        self.height = self._io.read_u4le()
        self.page_h_padding = self._io.read_u4le()
        self.page_v_padding = self._io.read_u4le()
        self.min_format_version = self._io.read_u4le()
        self.title_size = self._io.read_u4le()
        self._raw_title_blob = self._io.read_bytes(self.title_size)
        _io__raw_title_blob = KaitaiStream(BytesIO(self._raw_title_blob))
        self.title_blob = sdocx_text_wrapper.SdocxTextWrapper(_io__raw_title_blob)
        self.body_size = self._io.read_u4le()
        self._raw_body_blob = self._io.read_bytes(self.body_size)
        _io__raw_body_blob = KaitaiStream(BytesIO(self._raw_body_blob))
        self.body_blob = sdocx_text_wrapper.SdocxTextWrapper(_io__raw_body_blob)
        self._raw_pre_flex_gap = self._io.read_bytes(self.flex_offset - self._io.pos())
        _io__raw_pre_flex_gap = KaitaiStream(BytesIO(self._raw_pre_flex_gap))
        self.pre_flex_gap = SdocxNote.PreFlexGap(_io__raw_pre_flex_gap, self, self._root)
        if self.has_app_name:
            pass
            self.app_name = SdocxNote.ShortUtf16(self._io, self, self._root)

        if self.has_app_version:
            pass
            self.app_version = SdocxNote.AppVersion(self._io, self, self._root)

        if self.has_author_info:
            pass
            self.author_info = SdocxNote.AuthorInfo(self._io, self, self._root)

        if self.has_latitude_longitude:
            pass
            self.latitude_longitude = SdocxNote.GeoPosition(self._io, self, self._root)

        if self.has_template_uri:
            pass
            self.template_uri = SdocxNote.ShortUtf16(self._io, self, self._root)

        if self.has_last_edited_page:
            pass
            self.last_edited_page_index = self._io.read_u4le()

        if self.has_last_edited_page_image_and_time:
            pass
            self.last_edited_page_image_id = self._io.read_s4le()

        if self.has_last_edited_page_image_and_time:
            pass
            self.last_edited_page_time_us = self._io.read_s8le()

        if self.has_string_registry:
            pass
            self.string_registry = SdocxNote.StringRegistry(self._io, self, self._root)

        if self.has_body_text_font_size_delta:
            pass
            self.body_text_font_size_delta = self._io.read_s4le()

        if self.has_compatible_last_pen_info:
            pass
            self.compatible_last_pen_info = SdocxNote.PenInfoSimple(self._io, self, self._root)

        if self.has_voice_data:
            pass
            self.voice_data = SdocxNote.VoiceData(self._io, self, self._root)

        if self.has_attached_files:
            pass
            self.attached_files = SdocxNote.AttachedFiles(self._io, self, self._root)

        if self.has_last_pen_info:
            pass
            self.last_pen_info = SdocxNote.PenInfoFull(self._io, self, self._root)

        if self.has_server_check_point:
            pass
            self.server_check_point = self._io.read_s8le()

        if self.has_fixed_font:
            pass
            self.fixed_font = SdocxNote.ShortUtf16(self._io, self, self._root)

        if self.has_fixed_text_direction:
            pass
            self.fixed_text_direction = self._io.read_u4le()

        if self.has_fixed_background_theme:
            pass
            self.fixed_background_theme = self._io.read_u4le()

        if self.has_text_summarisation:
            pass
            self.text_summarisation = SdocxNote.ShortUtf16(self._io, self, self._root)

        if self.has_stroke_group_size:
            pass
            self.stroke_group_size = self._io.read_u4le()

        if self.has_app_custom_data:
            pass
            self.app_custom_data = SdocxNote.LongUtf16(self._io, self, self._root)

        self.trailing_hash = self._io.read_bytes(32)


    def _fetch_instances(self):
        pass
        self.property_flags._fetch_instances()
        self.field_flags._fetch_instances()
        self.note_id._fetch_instances()
        self.title_blob._fetch_instances()
        self.body_blob._fetch_instances()
        self.pre_flex_gap._fetch_instances()
        if self.has_app_name:
            pass
            self.app_name._fetch_instances()

        if self.has_app_version:
            pass
            self.app_version._fetch_instances()

        if self.has_author_info:
            pass
            self.author_info._fetch_instances()

        if self.has_latitude_longitude:
            pass
            self.latitude_longitude._fetch_instances()

        if self.has_template_uri:
            pass
            self.template_uri._fetch_instances()

        if self.has_last_edited_page:
            pass

        if self.has_last_edited_page_image_and_time:
            pass

        if self.has_last_edited_page_image_and_time:
            pass

        if self.has_string_registry:
            pass
            self.string_registry._fetch_instances()

        if self.has_body_text_font_size_delta:
            pass

        if self.has_compatible_last_pen_info:
            pass
            self.compatible_last_pen_info._fetch_instances()

        if self.has_voice_data:
            pass
            self.voice_data._fetch_instances()

        if self.has_attached_files:
            pass
            self.attached_files._fetch_instances()

        if self.has_last_pen_info:
            pass
            self.last_pen_info._fetch_instances()

        if self.has_server_check_point:
            pass

        if self.has_fixed_font:
            pass
            self.fixed_font._fetch_instances()

        if self.has_fixed_text_direction:
            pass

        if self.has_fixed_background_theme:
            pass

        if self.has_text_summarisation:
            pass
            self.text_summarisation._fetch_instances()

        if self.has_stroke_group_size:
            pass

        if self.has_app_custom_data:
            pass
            self.app_custom_data._fetch_instances()


    class AppVersion(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.AppVersion, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.major = self._io.read_u4le()
            self.minor = self._io.read_u4le()
            self.patch_name = SdocxNote.ShortUtf16(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            self.patch_name._fetch_instances()


    class AttachedFile(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.AttachedFile, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.name = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.file_id = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.name._fetch_instances()


    class AttachedFiles(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.AttachedFiles, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u2le()
            self.entries = []
            for i in range(self.count):
                self.entries.append(SdocxNote.AttachedFile(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class AuthorInfo(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.AuthorInfo, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.strings = []
            for i in range(3):
                self.strings.append(SdocxNote.ShortUtf16(self._io, self, self._root))

            self.image_id = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            for i in range(len(self.strings)):
                pass
                self.strings[i]._fetch_instances()



    class GeoPosition(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.GeoPosition, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.latitude = self._io.read_f8le()
            self.longitude = self._io.read_f8le()


        def _fetch_instances(self):
            pass


    class LongUtf16(KaitaiStruct):
        """A u32 character count followed by that many UTF-16LE code units."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.LongUtf16, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u4le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class PenInfoFull(KaitaiStruct):
        """Inclusive-length-prefixed pen record (field bit 15, last_pen_info)."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.PenInfoFull, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.total_size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.total_size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxNote.PenInfoFullBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class PenInfoFullBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.PenInfoFullBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.name = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.pen_size = self._io.read_f4le()
            self.color = self._io.read_bytes(4)
            self.is_curvable = self._io.read_u4le()
            self.advanced_settings = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.is_eraser_enabled = self._io.read_u4le()
            self.size_level = self._io.read_u4le()
            self.particle_density = self._io.read_u4le()
            self.particle_size = self._io.read_f4le()
            self.is_fixed_width = self._io.read_u4le()
            self.ui_color_hsv = []
            for i in range(3):
                self.ui_color_hsv.append(self._io.read_f4le())

            self.ui_color_info = self._io.read_u4le()
            if self._io.size() - self._io.pos() >= 4:
                pass
                self.is_fixed_opacity = self._io.read_u4le()

            if self._io.size() - self._io.pos() >= 4:
                pass
                self.is_auto_size_enabled = self._io.read_u4le()

            if self._io.size() - self._io.pos() >= 4:
                pass
                self.fit_ratio = self._io.read_f4le()



        def _fetch_instances(self):
            pass
            self.name._fetch_instances()
            self.advanced_settings._fetch_instances()
            for i in range(len(self.ui_color_hsv)):
                pass

            if self._io.size() - self._io.pos() >= 4:
                pass

            if self._io.size() - self._io.pos() >= 4:
                pass

            if self._io.size() - self._io.pos() >= 4:
                pass



    class PenInfoSimple(KaitaiStruct):
        """Un-prefixed pen record (field bit 12, compatible_last_pen_info)."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.PenInfoSimple, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.name = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.pen_size = self._io.read_f4le()
            self.color = self._io.read_bytes(4)
            self.is_curvable = self._io.read_u4le()
            self.advanced_settings = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.is_eraser_enabled = self._io.read_u4le()
            self.size_level = self._io.read_u4le()
            self.particle_density = self._io.read_u4le()
            self.ui_color_hsv = []
            for i in range(3):
                self.ui_color_hsv.append(self._io.read_f4le())

            self.ui_color_info = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.name._fetch_instances()
            self.advanced_settings._fetch_instances()
            for i in range(len(self.ui_color_hsv)):
                pass



    class PreFlexGap(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.PreFlexGap, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            if self._io.size() == 8:
                pass
                self.maybe_default_page_size = []
                for i in range(2):
                    self.maybe_default_page_size.append(self._io.read_u4le())


            self.rest = self._io.read_bytes_full()


        def _fetch_instances(self):
            pass
            if self._io.size() == 8:
                pass
                for i in range(len(self.maybe_default_page_size)):
                    pass




    class ShortUtf16(KaitaiStruct):
        """A u16 character count followed by that many UTF-16LE code units."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.ShortUtf16, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_len = self._io.read_u2le()
            self.value = (self._io.read_bytes(self.char_len * 2)).decode(u"UTF-16LE")


        def _fetch_instances(self):
            pass


    class StringRegistry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.StringRegistry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.byte_size = self._io.read_u4le()
            if self.byte_size > 0:
                pass
                self._raw_body = self._io.read_bytes(self.byte_size)
                _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
                self.body = SdocxNote.StringRegistryBody(_io__raw_body, self, self._root)



        def _fetch_instances(self):
            pass
            if self.byte_size > 0:
                pass
                self.body._fetch_instances()



    class StringRegistryBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.StringRegistryBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u2le()
            self.entries = []
            for i in range(self.count):
                self.entries.append(SdocxNote.StringRegistryEntry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class StringRegistryEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.StringRegistryEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.string_id = self._io.read_u4le()
            self.value = SdocxNote.ShortUtf16(self._io, self, self._root)


        def _fetch_instances(self):
            pass
            self.value._fetch_instances()


    class VarBitfield(KaitaiStruct):
        """`[u8 n_bytes][n-byte little-endian bitfield]`, n <= 4. On the corpus n
        is always 4.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.VarBitfield, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.len = self._io.read_u1()
            if self.len >= 1:
                pass
                self.b0 = self._io.read_u1()

            if self.len >= 2:
                pass
                self.b1 = self._io.read_u1()

            if self.len >= 3:
                pass
                self.b2 = self._io.read_u1()

            if self.len >= 4:
                pass
                self.b3 = self._io.read_u1()



        def _fetch_instances(self):
            pass
            if self.len >= 1:
                pass

            if self.len >= 2:
                pass

            if self.len >= 3:
                pass

            if self.len >= 4:
                pass


        @property
        def value(self):
            if hasattr(self, '_m_value'):
                return self._m_value

            self._m_value = (((self.b0 if self.len >= 1 else 0) | (self.b1 << 8 if self.len >= 2 else 0)) | (self.b2 << 16 if self.len >= 3 else 0)) | (self.b3 << 24 if self.len >= 4 else 0)
            return getattr(self, '_m_value', None)


    class VoiceData(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.VoiceData, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.count = self._io.read_u4le()
            self.recordings = []
            for i in range(self.count):
                self.recordings.append(SdocxNote.VoiceRecording(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.recordings)):
                pass
                self.recordings[i]._fetch_instances()



    class VoiceEvent(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.VoiceEvent, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.action = self._io.read_u4le()
            self.time_us = self._io.read_s8le()


        def _fetch_instances(self):
            pass


    class VoiceRecording(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.VoiceRecording, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.total_size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.total_size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxNote.VoiceRecordingBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class VoiceRecordingBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxNote.VoiceRecordingBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.file_id = self._io.read_u4le()
            self.name = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.duration_str = SdocxNote.ShortUtf16(self._io, self, self._root)
            self.created_time_ms = self._io.read_s8le()
            self.event_count = self._io.read_u4le()
            self.events = []
            for i in range(self.event_count):
                self.events.append(SdocxNote.VoiceEvent(self._io, self, self._root))

            self.precise_duration_ms = self._io.read_s8le()


        def _fetch_instances(self):
            pass
            self.name._fetch_instances()
            self.duration_str._fetch_instances()
            for i in range(len(self.events)):
                pass
                self.events[i]._fetch_instances()



    @property
    def has_app_custom_data(self):
        if hasattr(self, '_m_has_app_custom_data'):
            return self._m_has_app_custom_data

        self._m_has_app_custom_data = self.field_flags.value >> 22 & 1 != 0
        return getattr(self, '_m_has_app_custom_data', None)

    @property
    def has_app_name(self):
        if hasattr(self, '_m_has_app_name'):
            return self._m_has_app_name

        self._m_has_app_name = self.field_flags.value >> 0 & 1 != 0
        return getattr(self, '_m_has_app_name', None)

    @property
    def has_app_version(self):
        if hasattr(self, '_m_has_app_version'):
            return self._m_has_app_version

        self._m_has_app_version = self.field_flags.value >> 1 & 1 != 0
        return getattr(self, '_m_has_app_version', None)

    @property
    def has_attached_files(self):
        if hasattr(self, '_m_has_attached_files'):
            return self._m_has_attached_files

        self._m_has_attached_files = self.field_flags.value >> 14 & 1 != 0
        return getattr(self, '_m_has_attached_files', None)

    @property
    def has_author_info(self):
        if hasattr(self, '_m_has_author_info'):
            return self._m_has_author_info

        self._m_has_author_info = self.field_flags.value >> 2 & 1 != 0
        return getattr(self, '_m_has_author_info', None)

    @property
    def has_body_text_font_size_delta(self):
        if hasattr(self, '_m_has_body_text_font_size_delta'):
            return self._m_has_body_text_font_size_delta

        self._m_has_body_text_font_size_delta = self.field_flags.value >> 11 & 1 != 0
        return getattr(self, '_m_has_body_text_font_size_delta', None)

    @property
    def has_compatible_last_pen_info(self):
        if hasattr(self, '_m_has_compatible_last_pen_info'):
            return self._m_has_compatible_last_pen_info

        self._m_has_compatible_last_pen_info = self.field_flags.value >> 12 & 1 != 0
        return getattr(self, '_m_has_compatible_last_pen_info', None)

    @property
    def has_fixed_background_theme(self):
        if hasattr(self, '_m_has_fixed_background_theme'):
            return self._m_has_fixed_background_theme

        self._m_has_fixed_background_theme = self.field_flags.value >> 19 & 1 != 0
        return getattr(self, '_m_has_fixed_background_theme', None)

    @property
    def has_fixed_font(self):
        if hasattr(self, '_m_has_fixed_font'):
            return self._m_has_fixed_font

        self._m_has_fixed_font = self.field_flags.value >> 17 & 1 != 0
        return getattr(self, '_m_has_fixed_font', None)

    @property
    def has_fixed_text_direction(self):
        if hasattr(self, '_m_has_fixed_text_direction'):
            return self._m_has_fixed_text_direction

        self._m_has_fixed_text_direction = self.field_flags.value >> 18 & 1 != 0
        return getattr(self, '_m_has_fixed_text_direction', None)

    @property
    def has_last_edited_page(self):
        if hasattr(self, '_m_has_last_edited_page'):
            return self._m_has_last_edited_page

        self._m_has_last_edited_page = self.field_flags.value >> 7 & 1 != 0
        return getattr(self, '_m_has_last_edited_page', None)

    @property
    def has_last_edited_page_image_and_time(self):
        if hasattr(self, '_m_has_last_edited_page_image_and_time'):
            return self._m_has_last_edited_page_image_and_time

        self._m_has_last_edited_page_image_and_time = self.field_flags.value >> 9 & 1 != 0
        return getattr(self, '_m_has_last_edited_page_image_and_time', None)

    @property
    def has_last_pen_info(self):
        if hasattr(self, '_m_has_last_pen_info'):
            return self._m_has_last_pen_info

        self._m_has_last_pen_info = self.field_flags.value >> 15 & 1 != 0
        return getattr(self, '_m_has_last_pen_info', None)

    @property
    def has_latitude_longitude(self):
        if hasattr(self, '_m_has_latitude_longitude'):
            return self._m_has_latitude_longitude

        self._m_has_latitude_longitude = self.field_flags.value >> 3 & 1 != 0
        return getattr(self, '_m_has_latitude_longitude', None)

    @property
    def has_server_check_point(self):
        if hasattr(self, '_m_has_server_check_point'):
            return self._m_has_server_check_point

        self._m_has_server_check_point = self.field_flags.value >> 16 & 1 != 0
        return getattr(self, '_m_has_server_check_point', None)

    @property
    def has_string_registry(self):
        if hasattr(self, '_m_has_string_registry'):
            return self._m_has_string_registry

        self._m_has_string_registry = self.field_flags.value >> 10 & 1 != 0
        return getattr(self, '_m_has_string_registry', None)

    @property
    def has_stroke_group_size(self):
        if hasattr(self, '_m_has_stroke_group_size'):
            return self._m_has_stroke_group_size

        self._m_has_stroke_group_size = self.field_flags.value >> 21 & 1 != 0
        return getattr(self, '_m_has_stroke_group_size', None)

    @property
    def has_template_uri(self):
        if hasattr(self, '_m_has_template_uri'):
            return self._m_has_template_uri

        self._m_has_template_uri = self.field_flags.value >> 6 & 1 != 0
        return getattr(self, '_m_has_template_uri', None)

    @property
    def has_text_summarisation(self):
        if hasattr(self, '_m_has_text_summarisation'):
            return self._m_has_text_summarisation

        self._m_has_text_summarisation = self.field_flags.value >> 20 & 1 != 0
        return getattr(self, '_m_has_text_summarisation', None)

    @property
    def has_unhandled_field_bits(self):
        """True if any field bit outside the modeled set (0-3, 6, 7, 9-22) is set;
        the sequence after the gap would then be misaligned. Zero on the corpus.
        """
        if hasattr(self, '_m_has_unhandled_field_bits'):
            return self._m_has_unhandled_field_bits

        self._m_has_unhandled_field_bits = self.field_flags.value & 4286578992 != 0
        return getattr(self, '_m_has_unhandled_field_bits', None)

    @property
    def has_voice_data(self):
        if hasattr(self, '_m_has_voice_data'):
            return self._m_has_voice_data

        self._m_has_voice_data = self.field_flags.value >> 13 & 1 != 0
        return getattr(self, '_m_has_voice_data', None)


