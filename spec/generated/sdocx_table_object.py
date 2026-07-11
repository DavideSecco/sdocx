# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class SdocxTableObject(KaitaiStruct):
    """The body of a type-22 inline object (a table) embedded in the body text's
    `text_core::Common` frame inside `note.note`. Fed the object-body slice
    (`obj_size` bytes starting at the object's `body_off`).

    Decoded end-to-end and cross-checked field-by-field against
    `pysdocx.note_doc.parse_table_object` by `spec/tools/validate_table_object.py`
    (zero counterexamples on the corpus, including the Tabella4x3Regolare styled
    family with rendered-PDF ground truth). Narrative:
    docs/format/container/note-note/tables.md.

    Two size conventions coexist: SELF-SIZED records carry a `u4 size` counting
    from the size field's own offset; CHAIN records (rows, cells, paths, border
    blocks) carry a `u4 size` counting only the bytes after the field.

    Tables exist only in notes with `format_version >= 2035` (they *are* inline
    objects, which that version introduced), so the nested cell Common frames
    always carry the inline-object fields — no format-version parameter needed.
    """
    def __init__(self, _io, _parent=None, _root=None):
        super(SdocxTableObject, self).__init__(_io)
        self._parent = _parent
        self._root = _root or self
        self._read()

    def _read(self):
        self.wrap = SdocxTableObject.TableWrapRec(self._io, self, self._root)
        self.midpoints = SdocxTableObject.TableMidpointsRec(self._io, self, self._root)
        self.outline = SdocxTableObject.TableOutlineRec(self._io, self, self._root)
        self.content_size = self._io.read_u4le()
        self._raw_content = self._io.read_bytes(self.content_size - 4)
        _io__raw_content = KaitaiStream(BytesIO(self._raw_content))
        self.content = SdocxTableObject.TableContent(_io__raw_content, self, self._root)


    def _fetch_instances(self):
        pass
        self.wrap._fetch_instances()
        self.midpoints._fetch_instances()
        self.outline._fetch_instances()
        self.content._fetch_instances()

    class BorderBlock(KaitaiStruct):
        """Chain-sized block of 4 border entries. Entries 0/2 are the vertical
        edges/lines and 1/3 the horizontal ones (pair members never differed on
        the corpus, so left-vs-right / top-vs-bottom stay unresolved). A disabled
        border is fully zeroed. The radii are the rounded-corner radii (26.0 on
        the default outer frame, 0 on sharp "90°" frames and on grid lines).
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.BorderBlock, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.BorderBlockBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()
    class BorderBlockBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.BorderBlockBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.zero = self._io.read_u4le()
            self.t5 = self._io.read_bytes(5)
            if not self.t5 == b"\x01\x00\x02\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x01\x00\x02\x00\x00", self.t5, self._io, u"/types/border_block_body/seq/1")
            self.entries = []
            for i in range(4):
                self.entries.append(SdocxTableObject.BorderEntry(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.entries)):
                pass
                self.entries[i]._fetch_instances()



    class BorderEntry(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.BorderEntry, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.argb = self._io.read_u4le()
            self.width = self._io.read_f4le()
            self.radius_x = self._io.read_f4le()
            self.radius_y = self._io.read_f4le()


        def _fetch_instances(self):
            pass


    class CellMidpoints(KaitaiStruct):
        """As `table_midpoints` (page coords) plus two trailing sub-records of
        Unknown semantics: a 19-byte record whose payload holds a u4 255, and a
        16-byte tail starting with u4 12.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellMidpoints, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.tag = self._io.read_u2le()
            self.base = self._io.read_u4le()
            self.one = self._io.read_u2le()
            self.flags = self._io.read_u2le()
            self.point_count = self._io.read_u4le()
            self.points = []
            for i in range(self.point_count):
                self.points.append(SdocxTableObject.Point(self._io, self, self._root))

            self.four = self._io.read_u4le()
            self.zeros5 = self._io.read_bytes(5)
            if not self.zeros5 == b"\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00", self.zeros5, self._io, u"/types/cell_midpoints/seq/7")
            self.rec19_size = self._io.read_u4le()
            self.rec19_t5 = self._io.read_bytes(5)
            if not self.rec19_t5 == b"\x01\x00\x02\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x01\x00\x02\x00\x00", self.rec19_t5, self._io, u"/types/cell_midpoints/seq/9")
            self.rec19 = self._io.read_bytes(14)
            self.tail16 = self._io.read_bytes(16)
            if not self.tail16 == b"\x0C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x0C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", self.tail16, self._io, u"/types/cell_midpoints/seq/11")


        def _fetch_instances(self):
            pass
            for i in range(len(self.points)):
                pass
                self.points[i]._fetch_instances()



    class CellMidpointsRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellMidpointsRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.CellMidpoints(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class CellOutline(KaitaiStruct):
        """Self-sized cell-level outline record: flags, a rect, the outline path,
        then the cell's Common frame and a 2-byte `00 02` trailer.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellOutline, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.CellOutlineBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class CellOutlineBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellOutlineBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.tag = self._io.read_u2le()
            self.base = self._io.read_u4le()
            self.flags = self._io.read_bytes(7)
            self.four = self._io.read_u4le()
            self.pad_a = self._io.read_bytes(2)
            self.rect = SdocxTableObject.Rect(self._io, self, self._root)
            self.pad_b = self._io.read_bytes(2)
            self.path = SdocxTableObject.PathRec(self._io, self, self._root)
            self.pad = self._io.read_u1()
            self.frame_size = self._io.read_u4le()
            self._raw_frame = self._io.read_bytes(self.frame_size)
            _io__raw_frame = KaitaiStream(BytesIO(self._raw_frame))
            self.frame = SdocxTableObject.CommonFrame(_io__raw_frame, self, self._root)
            self.trailer = self._io.read_bytes(2)
            if not self.trailer == b"\x00\x02":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x02", self.trailer, self._io, u"/types/cell_outline_body/seq/11")


        def _fetch_instances(self):
            pass
            self.rect._fetch_instances()
            self.path._fetch_instances()
            self.frame._fetch_instances()


    class CellWrap(KaitaiStruct):
        """As `table_wrap` but without the trailing ts2/b3/table_index fields."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellWrap, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.pad = self._io.read_u2le()
            self.tag = self._io.read_u4le()
            self.head = self._io.read_bytes(8)
            self.version = self._io.read_u4le()
            self.uuid_len = self._io.read_u2le()
            self.uuid = (self._io.read_bytes(36)).decode(u"ASCII")
            self.ts1_us = self._io.read_s8le()
            self.bbox = SdocxTableObject.Rect(self._io, self, self._root)
            self.zeros5 = self._io.read_bytes(5)
            if not self.zeros5 == b"\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00", self.zeros5, self._io, u"/types/cell_wrap/seq/8")
            self.page_width = self._io.read_u4le()
            self.zero = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.bbox._fetch_instances()


    class CellWrapRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CellWrapRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.CellWrap(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class CommonFrame(KaitaiStruct):
        """A `text_core::Common` rich-text frame (here: a table cell's). Same layout
        as the note's title/body frames: text, span vector, paragraph vector,
        margins, gravity, sections, inline objects.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.CommonFrame, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.char_count = self._io.read_u4le()
            self.text_utf16 = self._io.read_bytes(self.char_count * 2)
            self.span_count = self._io.read_u4le()
            self.spans = []
            for i in range(self.span_count):
                self.spans.append(SdocxTableObject.SpanRec(self._io, self, self._root))

            self.paragraph_count = self._io.read_u4le()
            self.paragraphs = []
            for i in range(self.paragraph_count):
                self.paragraphs.append(SdocxTableObject.ParagraphRec(self._io, self, self._root))

            self.margins = []
            for i in range(4):
                self.margins.append(self._io.read_f4le())

            self.gravity = self._io.read_u1()
            self.section_count = self._io.read_u2le()
            self.sections = []
            for i in range(self.section_count):
                self.sections.append(SdocxTableObject.SectionPair(self._io, self, self._root))

            self.inline_present = self._io.read_u4le()
            self.inline_zero = self._io.read_u4le()
            if self.inline_present != 0:
                pass
                self.inline_object_count = self._io.read_u4le()

            if self.inline_present != 0:
                pass
                self.inline_objects = []
                for i in range(self.inline_object_count):
                    self.inline_objects.append(SdocxTableObject.InlineObject(self._io, self, self._root))




        def _fetch_instances(self):
            pass
            for i in range(len(self.spans)):
                pass
                self.spans[i]._fetch_instances()

            for i in range(len(self.paragraphs)):
                pass
                self.paragraphs[i]._fetch_instances()

            for i in range(len(self.margins)):
                pass

            for i in range(len(self.sections)):
                pass
                self.sections[i]._fetch_instances()

            if self.inline_present != 0:
                pass

            if self.inline_present != 0:
                pass
                for i in range(len(self.inline_objects)):
                    pass
                    self.inline_objects[i]._fetch_instances()




    class InlineObject(KaitaiStruct):
        """Opaque here; a nested table would recurse via this same spec."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.InlineObject, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.frame_size = self._io.read_u4le()
            self.blob = self._io.read_bytes(self.frame_size)


        def _fetch_instances(self):
            pass


    class ParagraphRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.ParagraphRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.record_size = self._io.read_u2le()
            self.paragraph_type = self._io.read_u4le()
            self.start = self._io.read_u4le()
            self.end = self._io.read_u4le()
            self.extra = self._io.read_bytes(self.record_size - 12)


        def _fetch_instances(self):
            pass


    class PathBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.PathBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.n_ops = self._io.read_u4le()
            self.ops = []
            for i in range(self.n_ops):
                self.ops.append(SdocxTableObject.PathOp(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.ops)):
                pass
                self.ops[i]._fetch_instances()



    class PathOp(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.PathOp, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.op = self._io.read_u1()
            if self.op != 6:
                pass
                self.x = self._io.read_f8le()

            if self.op != 6:
                pass
                self.y = self._io.read_f8le()



        def _fetch_instances(self):
            pass
            if self.op != 6:
                pass

            if self.op != 6:
                pass



    class PathRec(KaitaiStruct):
        """Chain-sized path record: u4 n_ops then opcodes 1 = moveto (f8 x, f8 y),
        2 = lineto (f8 x, f8 y), 6 = closepath (no point). Corpus paths are all
        closed rectangles.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.PathRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.PathBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class Point(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.Point, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.x = self._io.read_f8le()
            self.y = self._io.read_f8le()


        def _fetch_instances(self):
            pass


    class Rect(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.Rect, self).__init__(_io)
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


    class SectionPair(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.SectionPair, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.a = self._io.read_u4le()
            self.b = self._io.read_u4le()


        def _fetch_instances(self):
            pass


    class SpanRec(KaitaiStruct):
        """Character-style span with cell-local coordinates. Ground-truth-confirmed
        span types: 1 foreground_color (extra = LE 0xAARRGGBB), 3 font_size
        (extra = f4 pt), 5 bold / 6 italic / 7 underline / 20 strikethrough
        (extra = u4 bool). Payloads end with a constant zero u4.
        """
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.SpanRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.record_size = self._io.read_u2le()
            self.span_type = self._io.read_u4le()
            self.start = self._io.read_u4le()
            self.end = self._io.read_u4le()
            self.interval_type = self._io.read_u4le()
            self.extra = self._io.read_bytes(self.record_size - 16)


        def _fetch_instances(self):
            pass


    class TableCell(KaitaiStruct):
        """Chain record."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableCell, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.TableCellBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class TableCellBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableCellBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.zero = self._io.read_u4le()
            self.m0 = self._io.read_u1()
            self.styled = self._io.read_u1()
            self.m2 = self._io.read_bytes(3)
            if not self.m2 == b"\x02\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x02\x00\x00", self.m2, self._io, u"/types/table_cell_body/seq/3")
            self.col_index = self._io.read_u4le()
            self.one_a = self._io.read_u4le()
            self.one_b = self._io.read_u4le()
            self.fill_argb = self._io.read_u4le()
            self.bbox = SdocxTableObject.Rect(self._io, self, self._root)
            self.b1 = self._io.read_u1()
            self.inner_size = self._io.read_u4le()
            self.cwrap = SdocxTableObject.CellWrapRec(self._io, self, self._root)
            self.cmid = SdocxTableObject.CellMidpointsRec(self._io, self, self._root)
            self.coutline = SdocxTableObject.CellOutline(self._io, self, self._root)
            self.terminator = self._io.read_bytes(15)
            if not self.terminator == b"\x0F\x00\x00\x00\x02\x00\x00\x00\x00\x00\x01\x00\x02\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x0F\x00\x00\x00\x02\x00\x00\x00\x00\x00\x01\x00\x02\x00\x00", self.terminator, self._io, u"/types/table_cell_body/seq/14")


        def _fetch_instances(self):
            pass
            self.bbox._fetch_instances()
            self.cwrap._fetch_instances()
            self.cmid._fetch_instances()
            self.coutline._fetch_instances()


    class TableContent(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableContent, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.object_type = self._io.read_u2le()
            self.const15 = self._io.read_u2le()
            self.pad = self._io.read_u2le()
            self.head = self._io.read_bytes(3)
            self.content_u16 = self._io.read_u2le()
            self.n_cols = self._io.read_u4le()
            self.col_widths = []
            for i in range(self.n_cols):
                self.col_widths.append(self._io.read_f4le())

            self.n_rows = self._io.read_u4le()
            self.rows = []
            for i in range(self.n_rows):
                self.rows.append(SdocxTableObject.TableRow(self._io, self, self._root))

            self.tail_bbox = SdocxTableObject.Rect(self._io, self, self._root)
            self.outer_borders = SdocxTableObject.BorderBlock(self._io, self, self._root)
            self.n_col_min = self._io.read_u4le()
            self.col_width_min = []
            for i in range(self.n_col_min):
                self.col_width_min.append(self._io.read_f4le())

            self.n_col_max = self._io.read_u4le()
            self.col_width_max = []
            for i in range(self.n_col_max):
                self.col_width_max.append(self._io.read_f4le())

            self.table_width_max = self._io.read_f4le()
            self.grid_borders = SdocxTableObject.BorderBlock(self._io, self, self._root)
            self.theme_fill_argb = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            for i in range(len(self.col_widths)):
                pass

            for i in range(len(self.rows)):
                pass
                self.rows[i]._fetch_instances()

            self.tail_bbox._fetch_instances()
            self.outer_borders._fetch_instances()
            for i in range(len(self.col_width_min)):
                pass

            for i in range(len(self.col_width_max)):
                pass

            self.grid_borders._fetch_instances()


    class TableMidpoints(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableMidpoints, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.tag = self._io.read_u2le()
            self.base = self._io.read_u4le()
            self.one = self._io.read_u2le()
            self.flags = self._io.read_u2le()
            self.point_count = self._io.read_u4le()
            self.points = []
            for i in range(self.point_count):
                self.points.append(SdocxTableObject.Point(self._io, self, self._root))

            self.four = self._io.read_u4le()
            self.zeros5 = self._io.read_bytes(5)
            if not self.zeros5 == b"\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00", self.zeros5, self._io, u"/types/table_midpoints/seq/7")


        def _fetch_instances(self):
            pass
            for i in range(len(self.points)):
                pass
                self.points[i]._fetch_instances()



    class TableMidpointsRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableMidpointsRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.TableMidpoints(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class TableOutline(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableOutline, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.tag = self._io.read_u2le()
            self.base = self._io.read_u4le()
            self.flags = self._io.read_bytes(7)
            self.four = self._io.read_u4le()
            self.pad_a = self._io.read_bytes(2)
            self.rect = SdocxTableObject.Rect(self._io, self, self._root)
            self.pad_b = self._io.read_bytes(2)
            self.path = SdocxTableObject.PathRec(self._io, self, self._root)
            self.pad = self._io.read_u1()


        def _fetch_instances(self):
            pass
            self.rect._fetch_instances()
            self.path._fetch_instances()


    class TableOutlineRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableOutlineRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.TableOutline(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class TableRow(KaitaiStruct):
        """Chain record (size counts the bytes after the field)."""
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableRow, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.TableRowBody(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()


    class TableRowBody(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableRowBody, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.preamble = self._io.read_bytes(9)
            if not self.preamble == b"\x00\x00\x00\x00\x01\x00\x02\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x01\x00\x02\x00\x00", self.preamble, self._io, u"/types/table_row_body/seq/0")
            self.height = self._io.read_f4le()
            self.row_index = self._io.read_u4le()
            self.n_cols = self._io.read_u4le()
            self.cells = []
            for i in range(self.n_cols):
                self.cells.append(SdocxTableObject.TableCell(self._io, self, self._root))



        def _fetch_instances(self):
            pass
            for i in range(len(self.cells)):
                pass
                self.cells[i]._fetch_instances()



    class TableWrap(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableWrap, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.pad = self._io.read_u2le()
            self.tag = self._io.read_u4le()
            self.head = self._io.read_bytes(8)
            self.version = self._io.read_u4le()
            self.uuid_len = self._io.read_u2le()
            self.uuid = (self._io.read_bytes(36)).decode(u"ASCII")
            self.ts1_us = self._io.read_s8le()
            self.bbox = SdocxTableObject.Rect(self._io, self, self._root)
            self.zeros5 = self._io.read_bytes(5)
            if not self.zeros5 == b"\x00\x00\x00\x00\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x00\x00\x00\x00\x00", self.zeros5, self._io, u"/types/table_wrap/seq/8")
            self.ts2_us = self._io.read_s8le()
            self.page_width = self._io.read_u4le()
            self.zero = self._io.read_u4le()
            self.b3 = self._io.read_u1()
            self.table_index = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.bbox._fetch_instances()


    class TableWrapRec(KaitaiStruct):
        def __init__(self, _io, _parent=None, _root=None):
            super(SdocxTableObject.TableWrapRec, self).__init__(_io)
            self._parent = _parent
            self._root = _root
            self._read()

        def _read(self):
            self.size = self._io.read_u4le()
            self._raw_body = self._io.read_bytes(self.size - 4)
            _io__raw_body = KaitaiStream(BytesIO(self._raw_body))
            self.body = SdocxTableObject.TableWrap(_io__raw_body, self, self._root)


        def _fetch_instances(self):
            pass
            self.body._fetch_instances()
