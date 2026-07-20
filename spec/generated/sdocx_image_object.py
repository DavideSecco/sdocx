# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxImageObject(KaitaiStruct):
    """The crop flex of an imported-image placement record, fed the object bytes
    starting at the image's media-reference marker (`06 00 3e 00 00 00 02 00`,
    followed by the u32 media archive index). Everything before it — the common
    object header, the payload-geometry wrapper, the `01 00 04 20` placement marker
    + 4xf64 bbox + edge-midpoint geometry — is marker-scanned/decoded elsewhere
    (docs/format/container/page/object-types.md); this models only the crop, the
    newly decoded field.

    A field-flag byte's `0x40` bit marks a cropped image; when set, a 4xf64 rect
    gives where the FULL (uncropped) image would sit on the page (its aspect equals
    the source image's), and the placement bbox is the cropped window inside it —
    so the visible source sub-rect is that bbox normalized into this rect. Offsets
    are relative to the media reference and calibrated on the two cropped images in
    ImagesAllTrasnsformations (a page-object crop, aspect 3.076, and a note.note
    inline crop, aspect 2.786).
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxImageObject, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.media_ref_marker = self._io.read_bytes(8)
        if not self.media_ref_marker == b"\x06\x00\x3E\x00\x00\x00\x02\x00":
            raise kaitaistruct.ValidationNotEqualError(b"\x06\x00\x3E\x00\x00\x00\x02\x00", self.media_ref_marker, self._io, u"/seq/0")
        self.media_index = self._io.read_u4le()


    def _fetch_instances(self):
        pass
        _ = self.crop_flag
        if hasattr(self, '_m_crop_flag'):
            pass

        _ = self.crop_full_rect
        if hasattr(self, '_m_crop_full_rect'):
            pass
            self._m_crop_full_rect._fetch_instances()


    class Rect(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxImageObject.Rect, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.x0 = self._io.read_f8le()
            self.y0 = self._io.read_f8le()
            self.x1 = self._io.read_f8le()
            self.y1 = self._io.read_f8le()


        def _fetch_instances(self):
            pass


    @property
    def crop_flag(self):
        """Crop field-flag byte, at media-reference offset 12 + 57. Bit 0x40 marks a
        cropped image (65 = 0x41 when cropped, 17 = 0x11 when full).
        """
        if hasattr(self, '_m_crop_flag'):
            return self._m_crop_flag

        _pos = self._io.pos()
        self._io.seek(69)
        self._m_crop_flag = self._io.read_u1()
        self._io.seek(_pos)
        return getattr(self, '_m_crop_flag', None)

    @property
    def crop_full_rect(self):
        """The full (uncropped) image's page placement rectangle (media-reference
        offset 12 + 90). Present only when cropped.
        """
        if hasattr(self, '_m_crop_full_rect'):
            return self._m_crop_full_rect

        if self.is_cropped:
            pass
            _pos = self._io.pos()
            self._io.seek(102)
            self._m_crop_full_rect = SdocxImageObject.Rect(self._io, self, self._root)
            self._io.seek(_pos)

        return getattr(self, '_m_crop_full_rect', None)

    @property
    def is_cropped(self):
        if hasattr(self, '_m_is_cropped'):
            return self._m_is_cropped

        self._m_is_cropped = self.crop_flag & 64 != 0
        return getattr(self, '_m_is_cropped', None)


