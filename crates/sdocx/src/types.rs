/// A parsed `.sdocx` document containing pages and metadata.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Document {
    /// The pages in the document.
    pub pages: Vec<Page>,
    /// Document-level metadata.
    pub metadata: DocumentMetadata,
}

/// Document-level metadata extracted from the `.sdocx` archive.
#[derive(Debug, Clone, Default)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct DocumentMetadata {
    /// Creation timestamp in milliseconds since the Unix epoch.
    pub created_ms: Option<i64>,
    /// Last modification timestamp in milliseconds since the Unix epoch.
    pub modified_ms: Option<i64>,
    /// Background color of the document.
    pub background_color: Option<Color>,
    /// Whether Samsung Notes dark-mode compatibility is enabled.
    pub dark_mode_compatibility: Option<bool>,
    /// Default page dimensions as `(width, height)` in pixels.
    pub page_dimensions: Option<(u32, u32)>,
    /// Ordered list of page UUIDs.
    pub page_ids: Vec<String>,
    /// Embedded media assets from the archive.
    pub media_assets: Vec<MediaAsset>,
    /// Top-level typed note text from `note.note`, if present.
    pub note_text: Option<RichTextBox>,
    /// Tables decoded from `note.note` by the legacy marker-scan reader
    /// (`parse_tables`, clustered cell anchors). Kept as a corroborator; prefer
    /// [`Self::note_tables`] for byte-exact geometry.
    pub tables: Vec<Table>,
    /// Tables decoded from `note.note` by the byte-exact structural parser
    /// (the type-22 inline object; see `note_doc`). Authoritative: exact cell
    /// bboxes, column widths, per-cell fill, border blocks, and nested-frame
    /// text. Document-level like [`Self::tables`] (no page reference).
    pub note_tables: Vec<NoteTable>,
}

/// A table reconstructed from `note.note`'s cell records (ported from pysdocx
/// `parse_tables`: cells are read in row-major order and the grid is rebuilt by
/// clustering the cell anchor points — Samsung tables use equal-sized cells).
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Table {
    /// Number of rows.
    pub rows: usize,
    /// Number of columns.
    pub cols: usize,
    /// Table bounds in page coordinates, when the grid reconstructed cleanly.
    pub bbox: Option<BoundingBox>,
    /// X coordinates of the column grid lines (cols + 1 entries).
    pub x_edges: Vec<f64>,
    /// Y coordinates of the row grid lines (rows + 1 entries).
    pub y_edges: Vec<f64>,
    /// The cells, in document (row-major) order.
    pub cells: Vec<TableCell>,
}

/// One table cell: text, grid position, and its own rich-text style
/// (the same per-run TLV markers as the typed text, scoped to the cell).
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TableCell {
    /// Row index (0-based).
    pub row: usize,
    /// Column index (0-based).
    pub col: usize,
    /// Cell text.
    pub text: String,
    /// Cell anchor (bottom-left corner) in page coordinates.
    pub anchor: Point,
    /// Whether the whole cell is bold.
    pub bold: bool,
    /// Whether the whole cell is italic.
    pub italic: bool,
    /// Whether the whole cell is underlined.
    pub underline: bool,
    /// Explicit cell text color (includes the body-default gray; renderers
    /// decide what counts as "no explicit color").
    pub color: Option<Color>,
    /// Explicit cell font size in Samsung Notes logical units.
    pub font_size: Option<f32>,
}

/// A table decoded byte-exactly from `note.note`'s type-22 inline object
/// (`note_doc::note_tables`). Every field is a decoded format fact — cell
/// geometry, fills, and border blocks come straight from the serialized
/// structure, not a clustering heuristic.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct NoteTable {
    /// Table UUID (from the wrapper record).
    pub uuid: String,
    /// Table bounds in page coordinates (the wrapper's bbox).
    pub bbox: BoundingBox,
    /// Note page width carried in the wrapper (== `note.note` width on corpus).
    pub page_width: u32,
    /// 0-based index of this table among the note's tables (document order).
    pub table_index: u32,
    /// Number of rows.
    pub n_rows: usize,
    /// Number of columns.
    pub n_cols: usize,
    /// Per-column widths, page units (`col_widths` array).
    pub col_widths: Vec<f32>,
    /// Per-row heights, page units (row-chain order).
    pub row_heights: Vec<f32>,
    /// Outer-frame border block (4 entries; see [`TableBorder`]).
    pub outer_borders: [TableBorder; 4],
    /// Inner grid-line border block (4 entries).
    pub grid_borders: [TableBorder; 4],
    /// Per-column minimum width constraints (Marker; never varied on corpus).
    pub col_width_min: Vec<f32>,
    /// Per-column maximum width constraints (Marker).
    pub col_width_max: Vec<f32>,
    /// Max table width scalar (== note width − 2×72 margins on corpus).
    pub table_width_max: f32,
    /// Theme default header/highlight fill (0xAARRGGBB).
    pub theme_fill_argb: u32,
    /// The cells, in row-major order.
    pub cells: Vec<NoteTableCell>,
}

/// One border entry: ARGB colour plus stroke width and the two rounded-corner
/// radii. A disabled border is fully zeroed. In the style tail, entries 0/2 are
/// vertical edges/lines and 1/3 horizontal (the paired members never differ, so
/// left-vs-right / top-vs-bottom stay unresolved).
#[derive(Debug, Clone, Copy, Default, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TableBorder {
    /// Border colour, 0xAARRGGBB (0 == disabled).
    pub argb: u32,
    /// Stroke width, page units.
    pub width: f32,
    /// Rounded-corner radius X.
    pub radius_x: f32,
    /// Rounded-corner radius Y.
    pub radius_y: f32,
}

/// One cell of a [`NoteTable`], decoded byte-exactly.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct NoteTableCell {
    /// Row index (0-based).
    pub row: usize,
    /// Column index (0-based).
    pub col: usize,
    /// Cell bounds in page coordinates.
    pub bbox: BoundingBox,
    /// Cell UUID (from the cell wrapper record).
    pub uuid: String,
    /// Serialization version carried in the cell wrapper (4000 on corpus).
    pub version: u32,
    /// Table-wide "styled" flag from the cell preamble (set when the table
    /// carries explicit per-cell styling).
    pub styled: bool,
    /// Explicit cell background fill, 0xAARRGGBB (0 == theme default).
    pub fill_argb: u32,
    /// Cell text (from the nested Common frame; keeps trailing newlines).
    pub text: String,
    /// Character spans of the cell's Common frame (empty on a plain cell).
    pub spans: Vec<TableCellSpan>,
}

/// One character span of a table cell's Common frame. `span_type` follows the
/// `text_core` vocabulary (1 = foreground_color, 3 = font_size, 5 = bold,
/// 6 = italic, 7 = underline, 20 = strikethrough, …); a whole-cell style run
/// has `start == 0` and `end` == the cell text length.
#[derive(Debug, Clone, Copy)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TableCellSpan {
    /// Span type (`text_core` span vocabulary).
    pub span_type: u32,
    /// Inclusive start character index.
    pub start: u32,
    /// Exclusive end character index.
    pub end: u32,
    /// Interval type (Unknown semantics; constant on corpus).
    pub interval_type: u32,
    /// First u32 of the span payload: ARGB (colour), f32 bits (size), or bool.
    pub value: u32,
}

/// Whole-cell character style resolved from a cell's frame spans.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CellStyle {
    /// Whole cell is bold.
    pub bold: bool,
    /// Whole cell is italic.
    pub italic: bool,
    /// Whole cell is underlined.
    pub underline: bool,
    /// Whole cell is struck through.
    pub strikethrough: bool,
    /// Foreground colour (opaque spans only; includes the body-default gray).
    pub color: Option<Color>,
    /// Font size in Samsung Notes logical units (default 15.0 on the corpus).
    pub font_size: Option<f32>,
}

impl NoteTableCell {
    /// Whole-cell character style from the frame spans that cover the entire
    /// cell text (`start == 0`, `end == text length`). Mirrors pysdocx
    /// `table_cell_style`: 5 bold / 6 italic / 7 underline / 20 strikethrough
    /// (bool), 1 foreground_color (ARGB), 3 font_size (f32 bits).
    pub fn whole_cell_style(&self) -> CellStyle {
        let text_len = self.text.chars().count() as u32;
        let mut style = CellStyle::default();
        for span in &self.spans {
            if span.start != 0 || span.end != text_len {
                continue;
            }
            match span.span_type {
                5 => style.bold = span.value != 0,
                6 => style.italic = span.value != 0,
                7 => style.underline = span.value != 0,
                20 => style.strikethrough = span.value != 0,
                1 if span.value >> 24 == 0xFF => {
                    style.color = Some(Color {
                        r: (span.value >> 16) as u8,
                        g: (span.value >> 8) as u8,
                        b: span.value as u8,
                    });
                }
                3 => style.font_size = Some(f32::from_bits(span.value)),
                _ => {}
            }
        }
        style
    }
}

impl NoteTable {
    /// Page-local column/row grid-line coordinates (`x_edges` of length
    /// `n_cols + 1`, `y_edges` of length `n_rows + 1`) from the wrap bbox plus
    /// `col_widths` / `row_heights` — page-local even on geometry-edited tables,
    /// unlike the cell bboxes. Mirrors pysdocx `note_table_grid`.
    pub fn grid(&self) -> (Vec<f64>, Vec<f64>) {
        let mut x_edges = Vec::with_capacity(self.n_cols + 1);
        x_edges.push(self.bbox.x_min);
        for w in &self.col_widths {
            x_edges.push(x_edges.last().unwrap() + *w as f64);
        }
        let mut y_edges = Vec::with_capacity(self.n_rows + 1);
        y_edges.push(self.bbox.y_min);
        for h in &self.row_heights {
            y_edges.push(y_edges.last().unwrap() + *h as f64);
        }
        (x_edges, y_edges)
    }

    /// The 0-based index of the page this table is anchored to (the wrap
    /// `table_index` field — note.note's table→page reference; see docs
    /// tables.md). Named accessor so placement code reads the intent.
    pub fn page_index(&self) -> usize {
        self.table_index as usize
    }
}

/// A single page within a document.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Page {
    /// Unique identifier for the page.
    pub uuid: String,
    /// Page width in pixels.
    pub width: u32,
    /// Page height in pixels.
    pub height: u32,
    /// Bounding box enclosing page content; omitted when the serialized layer tree has no objects.
    pub content_bbox: Option<BoundingBox>,
    /// Page background color, if present in the page header.
    pub background_color: Option<Color>,
    /// Page template metadata, if present in the page header.
    pub template: Option<PageTemplate>,
    /// The strokes drawn on this page.
    pub strokes: Vec<Stroke>,
    /// Non-stroke page objects parsed from the page stream.
    pub elements: Vec<PageElement>,
}

/// An embedded media asset.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct MediaAsset {
    /// Archive path.
    pub name: String,
    /// MIME type, when recognized.
    pub mime_type: String,
    /// Raw media bytes.
    pub data: Vec<u8>,
}

impl MediaAsset {
    /// Decoded `<index>@` archive index from the member name — the index media
    /// references inside `.page`/`note.note` use (same currency as pysdocx).
    pub fn archive_index(&self) -> Option<u32> {
        let base = self.name.rsplit('/').next().unwrap_or(&self.name);
        base.split_once('@')?.0.parse().ok()
    }
}

/// A non-stroke page element.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum PageElement {
    /// A placed image object.
    Image {
        /// Placement box in page coordinates.
        bbox: BoundingBox,
        /// Index into `DocumentMetadata::media_assets`.
        media_index: usize,
    },
    /// A rich text object.
    TextBox(RichTextBox),
    /// An inserted shape object (shape tool / line-arrow tool).
    Shape(Shape),
    /// A sticky-note (attached sub-note) placement, shown collapsed. The
    /// attachment itself is a nested `.sdocx` media member and is not
    /// rendered recursively (matches pysdocx's "enumerate them" bar).
    StickyNote {
        /// Collapsed-square placement in page coordinates.
        bbox: BoundingBox,
        /// Archive media index of the attached sub-document
        /// (the `<index>@` prefix of its `media/` member).
        media_index: usize,
        /// Collapsed-square background color, when the property bag
        /// carries one (`skn_bg_color`, an Android ARGB color int).
        bg_color: Option<Color>,
    },
}

/// Decoded shape family. Mirrors pysdocx `SHAPE_TYPES` (pysdocx/page.py); codes not
/// yet mapped fall back to `Polygon` and still render from their decoded outline.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "serde", serde(rename_all = "snake_case"))]
pub enum ShapeKind {
    Ellipse,
    Triangle,
    Rectangle,
    Hexagon,
    Rhombus,
    Trapezoid,
    Pentagon,
    Star,
    Cross,
    Heart,
    RoundedRect,
    Freeform,
    FreeformSmooth,
    Arrow,
    Polygon,
}

/// One segment of a shape's raw outline path, exactly as stored (before
/// flattening) — 1-byte tag `1=MoveTo, 2=LineTo, 4=CubicBezierTo` in the file.
/// Lets a renderer draw a true curve instead of `Shape::points`' flattened
/// polyline approximation (pysdocx always flattens; this is strictly more
/// fidelity than the reference implementation exposes).
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum OutlineOp {
    MoveTo(Point),
    LineTo(Point),
    /// Cubic Bezier: two control points, then the end point.
    CurveTo(Point, Point, Point),
}

/// An inserted shape, decoded from its serialized vector path (ported from pysdocx
/// `parse_shapes_from_objects`, validated against the shape samples' ground truth).
///
/// `points` is the flattened true outline (already rotated / deformed), except for
/// ellipse (8 boundary points) and rounded-rect (4 edge midpoints), whose stored
/// outline path is degenerate — they keep the vertex list and are reconstructed at
/// render time (`ellipse_from_points` / `oriented_corners` in pysdocx render.py).
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Shape {
    /// Shape family.
    pub kind: ShapeKind,
    /// Raw type code from the shape marker; `None` for line/arrow objects,
    /// which are markerless.
    pub type_code: Option<u32>,
    /// Placement box in page coordinates.
    pub bbox: BoundingBox,
    /// Outline points in page coordinates (see struct docs).
    pub points: Vec<Point>,
    /// The raw (unflattened) outline path, when the shape has a real,
    /// non-degenerate stored path. `None` for ellipse/rounded-rect (degenerate —
    /// use `points`/the vertex list) and for arrows (no path at all).
    pub outline: Option<Vec<OutlineOp>>,
    /// Stroke color.
    pub color: Option<Color>,
    /// Pen line width.
    pub pen_width: Option<f32>,
    /// Whether the outline is closed (drawn back to its first point).
    pub closed: bool,
    /// Arrow only: arrowhead at the first point.
    pub head_start: bool,
    /// Arrow only: arrowhead at the last point.
    pub head_end: bool,
}

/// Parsed rich text box data.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct RichTextBox {
    /// Placement box in page coordinates.
    pub bbox: BoundingBox,
    /// Clockwise rotation in degrees, if present.
    pub rotation_degrees: Option<f64>,
    /// Full text content.
    pub text: String,
    /// Text foreground color.
    pub color: Option<Color>,
    /// Text highlight/fill color.
    pub highlight_color: Option<Color>,
    /// Whether underline styling is present.
    pub underline: bool,
    /// Font size in Samsung Notes logical units, when present.
    pub font_size: Option<f32>,
    /// Style runs using character indexes into `text`.
    pub runs: Vec<RichTextRun>,
    /// Per-run foreground colors (character indexes into `text`).
    pub colors: Vec<ColorRun>,
    /// Per-run highlight colors (character indexes into `text`).
    pub highlights: Vec<ColorRun>,
    /// Per-run font sizes in Samsung Notes logical units.
    pub font_sizes: Vec<FontSizeRun>,
    /// The 4 stored edge-midpoints of a rotated text-box frame, when present
    /// and self-consistent with `bbox` (see pysdocx `_text_box_frame_midpoints`).
    pub frame_midpoints: Option<[Point; 4]>,
}

/// A rich text style run.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct RichTextRun {
    /// Start character index, inclusive.
    pub start: usize,
    /// End character index, exclusive.
    pub end: usize,
    /// Whether the run is bold.
    pub bold: bool,
    /// Whether the run is italic.
    pub italic: bool,
    /// Whether the run is underlined.
    pub underline: bool,
    /// Whether the run is struck through.
    pub strikethrough: bool,
}

/// A per-run color (foreground or highlight) over character indexes.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ColorRun {
    /// Start character index, inclusive.
    pub start: usize,
    /// End character index, exclusive.
    pub end: usize,
    /// The run's color.
    pub color: Color,
}

/// A per-run font size over character indexes.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct FontSizeRun {
    /// Start character index, inclusive.
    pub start: usize,
    /// End character index, exclusive.
    pub end: usize,
    /// Font size in Samsung Notes logical units.
    pub size: f32,
}

/// Page template metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct PageTemplate {
    /// Raw Samsung Notes template identifier.
    pub id: u32,
    /// Template backing source.
    pub source: PageTemplateSource,
}

/// Page template backing source.
#[derive(Debug, Clone, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum PageTemplateSource {
    /// Built-in Samsung Notes page template (procedural background — lined / grid / dot / …).
    BuiltIn,
    /// PDF-backed page template: multi-page "Academic" templates (Notebook, Planner, …) and
    /// imported PDFs. The artwork is a real PDF embedded under `media/`; render by rasterising
    /// the referenced page. See `page_pdf_template` in `page.rs`.
    CustomPdf {
        /// Archive media index of the embedded `media/<index>@<name>.pdf`.
        media_index: u32,
        /// Zero-based page index within that PDF.
        page_index: u32,
    },
    /// Custom image selected from Samsung Notes' template picker. The page
    /// stores an app-private URI; newer exports may embed a media member whose
    /// basename matches `filename`.
    CustomImage {
        /// Basename of the image path stored in the page preamble.
        filename: String,
    },
}

/// A single pen stroke consisting of points and associated data.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Stroke {
    /// Bounding box of the stroke.
    pub bbox: BoundingBox,
    /// The (x, y) coordinates along the stroke path.
    pub points: Vec<Point>,
    /// Pressure values for each point, normalized to `[0.0, 1.0]`.
    pub pressures: Vec<f64>,
    /// Timestamps for each point in milliseconds since the Unix epoch.
    pub timestamps: Vec<i64>,
    /// Stylus tilt along the X axis for each point.
    pub tilt_x: Vec<i64>,
    /// Stylus tilt along the Y axis for each point.
    pub tilt_y: Vec<i64>,
    /// Stroke color, if present.
    pub color: Option<Color>,
    /// Pen width in pixels.
    pub pen_width: f32,
    /// Pen tool (0=pen, 1=fountain pen, 2=calligraphy pen, 3=pencil,
    /// 4=calligraphy brush; other values seen but not yet identified).
    /// `None` when no color marker was found at all.
    pub tool_id: Option<u8>,
    /// `true` for ink-pen-category tools, which have pressure-sensitive
    /// width (a fountain/calligraphy nib effect); `false` for highlighter/
    /// marker-category tools, which render at a constant width regardless
    /// of pressure (a flat felt tip).
    pub tapered: bool,
}

/// A 2D point.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Point {
    /// X coordinate.
    pub x: f64,
    /// Y coordinate.
    pub y: f64,
}

/// An RGB color.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Color {
    /// Red channel (0–255).
    pub r: u8,
    /// Green channel (0–255).
    pub g: u8,
    /// Blue channel (0–255).
    pub b: u8,
}

/// An axis-aligned bounding box.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct BoundingBox {
    /// Minimum X coordinate.
    pub x_min: f64,
    /// Minimum Y coordinate.
    pub y_min: f64,
    /// Maximum X coordinate.
    pub x_max: f64,
    /// Maximum Y coordinate.
    pub y_max: f64,
}

impl Default for BoundingBox {
    fn default() -> Self {
        Self {
            x_min: 0.0,
            y_min: 0.0,
            x_max: 0.0,
            y_max: 0.0,
        }
    }
}
