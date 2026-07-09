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
    /// Tables decoded from `note.note` (document-level, like the typed text;
    /// note.note carries no page reference, so placement is a render decision).
    pub tables: Vec<Table>,
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
    /// Bounding box enclosing all stroke content.
    pub content_bbox: BoundingBox,
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
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct PageTemplate {
    /// Raw Samsung Notes template identifier.
    pub id: u32,
    /// Template backing source.
    pub source: PageTemplateSource,
}

/// Page template backing source.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub enum PageTemplateSource {
    /// Built-in Samsung Notes page template.
    BuiltIn,
    /// Custom PDF-backed page template.
    CustomPdf {
        /// Zero-based PDF page index used as the template.
        page_index: u32,
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
