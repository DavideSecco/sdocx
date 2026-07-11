use std::io::{Read, Seek};

use crate::error::{Error, Result};
use crate::page::parse_page;
use crate::types::{
    BoundingBox, Color, Document, DocumentMetadata, MediaAsset, Page, RichTextBox,
    Table, TableCell,
};

/// Parse a `.sdocx` ZIP archive from a reader.
pub fn parse_from_reader<R: Read + Seek>(reader: R) -> Result<Document> {
    let mut archive = zip::ZipArchive::new(reader)?;

    let mut metadata = DocumentMetadata::default();

    // Parse end_tag.bin (optional — graceful degradation)
    if let Ok(mut entry) = archive.by_name("end_tag.bin") {
        let mut buf = Vec::new();
        entry.read_to_end(&mut buf)?;
        parse_end_tag(&buf, &mut metadata);
    }

    let mut note_text = None;

    // Parse note.note (optional)
    if let Ok(mut entry) = archive.by_name("note.note") {
        let mut buf = Vec::new();
        entry.read_to_end(&mut buf)?;
        parse_note_note(&buf, &mut metadata);
        metadata.tables = parse_tables(&buf);
        note_text = parse_note_text(&buf);
    }

    // Parse pageIdInfo.dat (optional)
    if let Ok(mut entry) = archive.by_name("pageIdInfo.dat") {
        let mut buf = Vec::new();
        entry.read_to_end(&mut buf)?;
        parse_page_id_info(&buf, &mut metadata);
    }

    // Find and parse all .page files
    let page_names: Vec<String> = (0..archive.len())
        .filter_map(|i| {
            let entry = archive.by_index(i).ok()?;
            let name = entry.name().to_string();
            if name.ends_with(".page") {
                Some(name)
            } else {
                None
            }
        })
        .collect();

    if page_names.is_empty() {
        return Err(Error::Format("no .page files found in archive".into()));
    }

    metadata.media_assets = parse_media_assets(&mut archive)?;

    let mut pages: Vec<Page> = Vec::with_capacity(page_names.len());
    for name in &page_names {
        let mut entry = archive.by_name(name)?;
        let mut buf = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut buf)?;
        pages.push(parse_page(&buf)?);
    }

    if let (Some(page), Some(text)) = (pages.first_mut(), note_text.clone()) {
        page.elements.push(crate::types::PageElement::TextBox(text));
    }
    metadata.note_text = note_text;

    Ok(Document { pages, metadata })
}

/// Extract timestamps from `end_tag.bin`.
fn parse_end_tag(data: &[u8], metadata: &mut DocumentMetadata) {
    if data.len() < 0x58 {
        return;
    }
    let created = i64::from_le_bytes(data[0x48..0x50].try_into().unwrap());
    let modified = i64::from_le_bytes(data[0x50..0x58].try_into().unwrap());
    metadata.created_ms = Some(created);
    metadata.modified_ms = Some(modified);
}

/// Extract background color and page dimensions from `note.note`.
fn parse_note_note(data: &[u8], metadata: &mut DocumentMetadata) {
    // ⚠ MISLABEL (RE 2026-07-09): this reads `(u32 @ 0x04) & 0x0800`, but 0x04 is
    // inside note.note's length-prefixed `property_flags` bitfield, so this masks
    // no clean semantic bit. The decoded format has NO "dark mode" flag; the only
    // theme signal is `fixed_background_theme` (field-flags bit 19: 0 light/1 dark/
    // 2 default), which is `default`/absent across the whole corpus. This value is
    // therefore meaningless and MUST NOT drive rendering — the page paper color
    // (per-`.page`, see page.rs `page_background_color`) is the real signal.
    // Kept only until sdocx-render/-cli (reference SVG path) stop reading it.
    if data.len() >= 0x08 {
        let flags = u32::from_le_bytes(data[0x04..0x08].try_into().unwrap());
        metadata.dark_mode_compatibility = Some(flags & 0x0800 != 0);
    }

    // Page dimensions at 0x28, 0x2C
    if data.len() >= 0x30 {
        let w = u32::from_le_bytes(data[0x28..0x2C].try_into().unwrap());
        let h = u32::from_le_bytes(data[0x2C..0x30].try_into().unwrap());
        if w > 0 && h > 0 {
            metadata.page_dimensions = Some((w, h));
        }
    }

    // Background color: pattern [18 00] [00 00 01 00 00 00] [R] [G] [B] [FF]
    if data.len() >= 12 {
        for i in 0..data.len() - 12 {
            if data[i] == 0x18
                && data[i + 1] == 0x00
                && data[i + 2..i + 8] == [0x00, 0x00, 0x01, 0x00, 0x00, 0x00]
                && data[i + 11] == 0xFF
            {
                metadata.background_color = Some(Color {
                    r: data[i + 8],
                    g: data[i + 9],
                    b: data[i + 10],
                });
                break;
            }
        }
    }
}

/// Collect image media member names, ordered by their numeric index prefix.
fn media_member_names<R: Read + Seek>(archive: &mut zip::ZipArchive<R>) -> Vec<String> {
    let mut names: Vec<String> = (0..archive.len())
        .filter_map(|i| {
            let name = archive.by_index(i).ok()?.name().to_string();
            let lower = name.to_ascii_lowercase();
            // Renderable media members are `media/<index>@...`. Extensions are
            // unreliable — pasted images are extensionless JPEGs — so filter by
            // the indexed prefix and exclude Samsung-internal `.spi` previews.
            if name.starts_with("media/")
                && media_archive_index(&name).is_some()
                && !lower.ends_with(".spi")
            {
                Some(name)
            } else {
                None
            }
        })
        .collect();
    names.sort_by_key(|name| media_archive_index(name).unwrap_or(u32::MAX));
    names
}

fn mime_for(name: &str) -> &'static str {
    let lower = name.to_ascii_lowercase();
    if lower.ends_with(".png") {
        "image/png"
    } else if lower.ends_with(".webp") {
        "image/webp"
    } else {
        "image/jpeg"
    }
}

fn parse_media_assets<R: Read + Seek>(archive: &mut zip::ZipArchive<R>) -> Result<Vec<MediaAsset>> {
    let names = media_member_names(archive);
    let mut assets = Vec::with_capacity(names.len());
    for name in names {
        let mut entry = archive.by_name(&name)?;
        let mut data = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut data)?;
        let mime_type = mime_for(&name).to_string();
        assets.push(MediaAsset {
            name,
            mime_type,
            data,
        });
    }
    Ok(assets)
}

/// Numeric `<index>@` prefix of a media member's basename, when present. Image
/// placements inside `.page` files reference media by this archive index, which
/// is sparse — NOT the position in the ordered media list.
fn media_archive_index(name: &str) -> Option<u32> {
    let base = name.rsplit('/').next().unwrap_or(name);
    base.split_once('@')?.0.parse().ok()
}

/// Position of each `<index>@` archive index within the ordered media list.
///
/// The decoded archive index is the ONLY media currency parsers expose (same as
/// pysdocx): `PageElement::Image.media_index`, sticky notes, and the PDF-backed
/// template all carry it verbatim. This map exists so the fetch APIs
/// ([`Reader::media_bytes`], [`Reader::media_asset`]) can resolve it to a slot in
/// the ordered `media_assets` list internally — consumers never remap.
fn media_index_positions(names: &[String]) -> std::collections::HashMap<usize, usize> {
    names
        .iter()
        .enumerate()
        .filter_map(|(pos, n)| Some((media_archive_index(n)? as usize, pos)))
        .collect()
}

/// A media manifest (names + mime, no bytes) for lazy loading.
fn media_manifest<R: Read + Seek>(archive: &mut zip::ZipArchive<R>) -> (Vec<String>, Vec<MediaAsset>) {
    let names = media_member_names(archive);
    let assets = names
        .iter()
        .map(|name| MediaAsset {
            name: name.clone(),
            mime_type: mime_for(name).to_string(),
            data: Vec::new(),
        })
        .collect();
    (names, assets)
}

/// Order the present `.page` member names by the `pageIdInfo` UUID order, keeping
/// any unreferenced pages at the end (never dropping a page).
fn order_pages(page_ids: &[String], present: &mut Vec<String>) -> Vec<String> {
    if page_ids.is_empty() {
        return std::mem::take(present);
    }
    let mut ordered = Vec::with_capacity(present.len());
    for id in page_ids {
        let target = format!("{id}.page");
        if let Some(pos) = present
            .iter()
            .position(|n| *n == target || n.ends_with(&target) || n.contains(id.as_str()))
        {
            ordered.push(present.remove(pos));
        }
    }
    ordered.append(present);
    ordered
}

fn parse_note_text(data: &[u8]) -> Option<RichTextBox> {
    let (text, text_end) = first_utf16_text(data)?;
    // note.note's typed text reuses the same TLV style-run families as in-page
    // text boxes, with global character indexes (see pysdocx note.py).
    let text_len = text.chars().count();
    let styles = crate::page::scan_rich_text_styles(data, text_end, text_len, text_len);
    Some(RichTextBox {
        // `note.note` stores the typed note body as the default page text layer. The body itself
        // carries leading blank lines, so the renderer can place it from the page origin.
        bbox: BoundingBox {
            x_min: 0.0,
            y_min: 0.0,
            x_max: 0.0,
            y_max: 0.0,
        },
        rotation_degrees: None,
        text,
        color: styles.colors.first().map(|c| c.color),
        highlight_color: styles.highlights.first().map(|c| c.color),
        underline: styles.runs.iter().any(|r| r.underline),
        font_size: styles.font_sizes.first().map(|f| f.size),
        runs: styles.runs,
        colors: styles.colors,
        highlights: styles.highlights,
        font_sizes: styles.font_sizes,
        frame_midpoints: None,
    })
}

// ---------------------------------------------------------------------------
// Tables — ported from pysdocx note.py `parse_tables` + `_cell_style`.
//
// Cell records in note.note: `06 00 <u16 kind> 00 00 <u32 char_count>` with
// kind ∈ {0x8D, 0x95, 0xCD}, UTF-16LE text after, and the cell's page-coords
// anchor (bottom-left corner) as two f64 right before the marker. Each cell's
// TLV style block follows its text. The row/column grid is reconstructed by
// clustering the anchors (Samsung tables use equal-sized cells).
// ---------------------------------------------------------------------------

const TABLE_CELL_PREFIX: [u8; 2] = [0x06, 0x00];
const TABLE_CELL_KINDS: [u16; 3] = [0x8D, 0x95, 0xCD];
const TABLE_CELL_MARKER_LEN: usize = 10;
const TABLE_ANCHOR_X_BACK: usize = 16;
const TABLE_ANCHOR_Y_BACK: usize = 8;
const CELL_STYLE_WINDOW: usize = 200;

fn read_u16_at(data: &[u8], off: usize) -> Option<u16> {
    Some(u16::from_le_bytes(data.get(off..off + 2)?.try_into().ok()?))
}
fn read_u32_at(data: &[u8], off: usize) -> Option<u32> {
    Some(u32::from_le_bytes(data.get(off..off + 4)?.try_into().ok()?))
}
fn read_f64_at(data: &[u8], off: usize) -> Option<f64> {
    Some(f64::from_le_bytes(data.get(off..off + 8)?.try_into().ok()?))
}

/// One cell's whole-cell style runs from the TLV block right after its text.
/// Only runs spanning the cell exactly (start=0, end=char_count) are accepted,
/// so a run window overrunning into the next cell can't be mistaken for this
/// one's (pysdocx `_cell_style`).
fn cell_style(note: &[u8], cell_end: usize, char_count: usize) -> (bool, bool, bool, Option<Color>, Option<f32>) {
    let window = &note[cell_end..note.len().min(cell_end + CELL_STYLE_WINDOW)];
    let find = |tag: u8| -> Option<(usize, usize, u32)> {
        let marker = [0x18, 0x00, tag, 0x00];
        let i = window.windows(4).position(|w| w == marker)?;
        if i + 22 > window.len() {
            return None;
        }
        Some((
            read_u32_at(window, i + 6)? as usize,
            read_u32_at(window, i + 10)? as usize,
            read_u32_at(window, i + 18)?,
        ))
    };
    let whole_cell = |run: Option<(usize, usize, u32)>| -> Option<u32> {
        run.filter(|&(start, end, _)| start == 0 && end == char_count)
            .map(|(_, _, enabled)| enabled)
    };

    let bold = whole_cell(find(0x05)).is_some_and(|v| v != 0);
    let italic = whole_cell(find(0x06)).is_some_and(|v| v != 0);
    let underline = whole_cell(find(0x07)).is_some_and(|v| v != 0);
    let color = whole_cell(find(0x01))
        .filter(|argb| argb >> 24 == 0xFF)
        .map(|argb| Color {
            r: (argb >> 16) as u8,
            g: (argb >> 8) as u8,
            b: argb as u8,
        });
    let font_size = whole_cell(find(0x03))
        .map(|bits| f32::from_le_bytes(bits.to_le_bytes()))
        .filter(|size| size.is_finite() && (4.0..=200.0).contains(size));
    (bold, italic, underline, color, font_size)
}

/// Collapse near-equal coordinates (grid lines) into single averaged values.
fn cluster(mut values: Vec<f64>, tol: f64) -> Vec<f64> {
    values.sort_by(|a, b| a.total_cmp(b));
    let mut clusters: Vec<Vec<f64>> = Vec::new();
    for v in values {
        match clusters.last_mut() {
            Some(c) if v - *c.last().unwrap() <= tol => c.push(v),
            _ => clusters.push(vec![v]),
        }
    }
    clusters
        .iter()
        .map(|c| c.iter().sum::<f64>() / c.len() as f64)
        .collect()
}

/// Extract tables from `note.note` (pysdocx `parse_tables`).
fn parse_tables(note: &[u8]) -> Vec<Table> {
    struct RawCell {
        text: String,
        anchor: (f64, f64),
        style: (bool, bool, bool, Option<Color>, Option<f32>),
    }
    let mut cells: Vec<RawCell> = Vec::new();
    let mut off = 0usize;
    while let Some(rel) = note[off..]
        .windows(2)
        .position(|w| w == TABLE_CELL_PREFIX)
    {
        let m = off + rel;
        off = m + 1;
        if m + TABLE_CELL_MARKER_LEN > note.len() {
            break;
        }
        let Some(kind) = read_u16_at(note, m + 2) else { break };
        let Some(char_count) = read_u32_at(note, m + 6).map(|v| v as usize) else { break };
        if !TABLE_CELL_KINDS.contains(&kind) || !(1..=512).contains(&char_count) {
            continue;
        }
        let text_start = m + TABLE_CELL_MARKER_LEN;
        let text_end = text_start + char_count * 2;
        if text_end > note.len() {
            continue;
        }
        let mut units: Vec<u16> = Vec::new();
        let mut end = text_start;
        while end + 2 <= text_end {
            let unit = u16::from_le_bytes([note[end], note[end + 1]]);
            if !(0x20..=0xD7FF).contains(&unit) {
                break;
            }
            units.push(unit);
            end += 2;
        }
        if units.is_empty() {
            continue;
        }
        let Some(x) = m.checked_sub(TABLE_ANCHOR_X_BACK).and_then(|o| read_f64_at(note, o)) else {
            continue;
        };
        let Some(y) = m.checked_sub(TABLE_ANCHOR_Y_BACK).and_then(|o| read_f64_at(note, o)) else {
            continue;
        };
        if !(0.0..=3000.0).contains(&x) || !(0.0..=4000.0).contains(&y) {
            continue;
        }
        let Ok(text) = String::from_utf16(&units) else {
            continue;
        };
        cells.push(RawCell {
            text,
            anchor: (x, y),
            style: cell_style(note, text_end, char_count),
        });
    }

    if cells.is_empty() {
        return Vec::new();
    }

    let xs = cluster(cells.iter().map(|c| c.anchor.0).collect(), 8.0);
    let ys = cluster(cells.iter().map(|c| c.anchor.1).collect(), 8.0);
    let (cols, rows) = (xs.len(), ys.len());

    let col_w = if cols > 1 { (xs[cols - 1] - xs[0]) / (cols - 1) as f64 } else { 0.0 };
    let row_h = if rows > 1 { (ys[rows - 1] - ys[0]) / (rows - 1) as f64 } else { 0.0 };
    // Anchors are bottom-left corners: xs[0] is the table's left edge; the row
    // anchors are bottoms, so the table top is one row-height above row 0's.
    let x_edges: Vec<f64> = (0..=cols).map(|i| xs[0] + i as f64 * col_w).collect();
    let y_edges: Vec<f64> = (0..=rows).map(|i| ys[0] - row_h + i as f64 * row_h).collect();

    let nearest = |edges: &[f64], v: f64| -> usize {
        edges
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| (*a - v).abs().total_cmp(&(*b - v).abs()))
            .map(|(i, _)| i)
            .unwrap_or(0)
    };
    let table_cells = cells
        .into_iter()
        .map(|c| {
            let (bold, italic, underline, color, font_size) = c.style;
            TableCell {
                row: nearest(&ys, c.anchor.1),
                col: nearest(&xs, c.anchor.0),
                text: c.text,
                anchor: crate::types::Point {
                    x: c.anchor.0,
                    y: c.anchor.1,
                },
                bold,
                italic,
                underline,
                color,
                font_size,
            }
        })
        .collect();

    vec![Table {
        rows,
        cols,
        bbox: Some(BoundingBox {
            x_min: x_edges[0],
            y_min: y_edges[0],
            x_max: x_edges[cols],
            y_max: y_edges[rows],
        }),
        x_edges,
        y_edges,
        cells: table_cells,
    }]
}

fn first_utf16_text(data: &[u8]) -> Option<(String, usize)> {
    let mut offset = 0;
    while offset + 6 <= data.len() {
        let mut end = offset;
        let mut units = Vec::new();
        while end + 2 <= data.len() {
            let unit = u16::from_le_bytes(data[end..end + 2].try_into().ok()?);
            let printable = unit == 0x0A || (0x20..=0xD7FF).contains(&unit);
            if !printable {
                break;
            }
            units.push(unit);
            end += 2;
        }
        let text = String::from_utf16(&units).ok()?;
        let trimmed = text.trim();
        if trimmed.chars().filter(|c| !c.is_whitespace()).count() >= 3
            && looks_like_note_text(trimmed)
        {
            return Some((text, end));
        }
        offset += 2;
    }
    None
}

fn looks_like_note_text(text: &str) -> bool {
    let mut total = 0;
    let mut common = 0;
    for ch in text.chars() {
        if ch.is_whitespace() {
            continue;
        }
        total += 1;
        if ch.is_ascii_alphanumeric() || ch.is_ascii_punctuation() {
            common += 1;
        }
    }
    total >= 3 && common * 4 >= total * 3
}

/// Extract page UUIDs from `pageIdInfo.dat`.
fn parse_page_id_info(data: &[u8], metadata: &mut DocumentMetadata) {
    if data.len() < 0x24 {
        return;
    }
    let count = u16::from_le_bytes(data[0x20..0x22].try_into().unwrap()) as usize;
    let mut offset = 0x22;

    for _ in 0..count {
        if offset + 2 > data.len() {
            break;
        }
        let char_len = u16::from_le_bytes(data[offset..offset + 2].try_into().unwrap()) as usize;
        offset += 2;
        if offset + char_len * 2 > data.len() {
            break;
        }
        let uuid: String = data[offset..offset + char_len * 2]
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .map(|c| char::from_u32(c as u32).unwrap_or('\u{FFFD}'))
            .collect();
        metadata.page_ids.push(uuid);
        offset += char_len * 2;
    }
}

/// A lazily-parsed `.sdocx`.
///
/// [`parse`](crate::parse) reads the whole document (every page's geometry and
/// every media blob) into memory up front — fine for small notes, but a 66-page
/// note is hundreds of MB and can exhaust memory. `Reader` instead reads only the
/// metadata and the page/media manifests on [`open`](Reader::open), then parses a
/// single page or media blob on demand. Pages are returned in `pageIdInfo` order.
pub struct Reader<R: Read + Seek> {
    archive: zip::ZipArchive<R>,
    metadata: DocumentMetadata,
    page_names: Vec<String>,
    media_names: Vec<String>,
    /// Decoded `<index>@` archive index → position in `media_names`/`media_assets`.
    media_index_map: std::collections::HashMap<usize, usize>,
}

impl<R: Read + Seek> Reader<R> {
    /// Open an archive and read metadata + manifests only (no page/media decode).
    pub fn open(reader: R) -> Result<Self> {
        let mut archive = zip::ZipArchive::new(reader)?;
        let mut metadata = DocumentMetadata::default();

        if let Ok(mut entry) = archive.by_name("end_tag.bin") {
            let mut buf = Vec::new();
            entry.read_to_end(&mut buf)?;
            parse_end_tag(&buf, &mut metadata);
        }
        let mut note_text = None;
        if let Ok(mut entry) = archive.by_name("note.note") {
            let mut buf = Vec::new();
            entry.read_to_end(&mut buf)?;
            parse_note_note(&buf, &mut metadata);
            metadata.tables = parse_tables(&buf);
            note_text = parse_note_text(&buf);
        }
        if let Ok(mut entry) = archive.by_name("pageIdInfo.dat") {
            let mut buf = Vec::new();
            entry.read_to_end(&mut buf)?;
            parse_page_id_info(&buf, &mut metadata);
        }
        metadata.note_text = note_text;

        let mut present: Vec<String> = (0..archive.len())
            .filter_map(|i| {
                let name = archive.by_index(i).ok()?.name().to_string();
                name.ends_with(".page").then_some(name)
            })
            .collect();
        if present.is_empty() {
            return Err(Error::Format("no .page files found in archive".into()));
        }
        let page_names = order_pages(&metadata.page_ids, &mut present);

        let (media_names, media_assets) = media_manifest(&mut archive);
        metadata.media_assets = media_assets;
        let media_index_map = media_index_positions(&media_names);

        Ok(Reader {
            archive,
            metadata,
            page_names,
            media_names,
            media_index_map,
        })
    }

    /// Decoded media archive index → position in `media_assets`. Fetch by raw
    /// index via [`Reader::media_bytes`]/[`Reader::media_asset`] instead; this is
    /// exposed only for callers that need to enumerate/correlate the asset list.
    pub fn media_index_map(&self) -> &std::collections::HashMap<usize, usize> {
        &self.media_index_map
    }

    /// Look up a media asset (name/mime, no bytes) by its decoded `<index>@`
    /// archive index — the index page elements and PDF templates carry.
    pub fn media_asset(&self, archive_index: usize) -> Option<&MediaAsset> {
        let pos = *self.media_index_map.get(&archive_index)?;
        self.metadata.media_assets.get(pos)
    }

    /// Document-level metadata (media assets carry names/mime but no bytes here).
    pub fn metadata(&self) -> &DocumentMetadata {
        &self.metadata
    }

    /// Number of pages.
    pub fn page_count(&self) -> usize {
        self.page_names.len()
    }

    /// Parse a single page by index (in `pageIdInfo` order).
    /// Extract one page's raw bytes from the archive without parsing. Parsing
    /// (`parse_page`) is a pure function of these bytes, so callers that hold a
    /// lock around the `Reader` can extract under the lock and parse outside it,
    /// letting page parses run in parallel.
    pub fn page_bytes(&mut self, index: usize) -> Result<Vec<u8>> {
        let name = self
            .page_names
            .get(index)
            .ok_or_else(|| Error::Format("page index out of range".into()))?
            .clone();
        let mut entry = self.archive.by_name(&name)?;
        let mut buf = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut buf)?;
        Ok(buf)
    }

    pub fn page(&mut self, index: usize) -> Result<Page> {
        let buf = self.page_bytes(index)?;
        let mut page = parse_page(&buf)?;
        // The typed note body is rendered as the first page's text layer, matching
        // `parse_from_reader`.
        if index == 0
            && let Some(text) = self.metadata.note_text.clone() {
                page.elements.push(crate::types::PageElement::TextBox(text));
            }
        Ok(page)
    }

    /// Read a page's pixel dimensions from its header alone — cheap (only the
    /// first ~30 bytes are decompressed), for laying out a continuous scroll view
    /// without parsing every page's strokes.
    pub fn page_size(&mut self, index: usize) -> Result<(u32, u32)> {
        let name = self
            .page_names
            .get(index)
            .ok_or_else(|| Error::Format("page index out of range".into()))?
            .clone();
        let mut entry = self.archive.by_name(&name)?;
        let mut hdr = [0u8; 0x1E];
        let mut read = 0;
        while read < hdr.len() {
            let n = entry.read(&mut hdr[read..])?;
            if n == 0 {
                break;
            }
            read += n;
        }
        if read < 0x1E {
            return Err(Error::Format("page header too short".into()));
        }
        let w = u32::from_le_bytes(hdr[0x16..0x1A].try_into().unwrap());
        let h = u32::from_le_bytes(hdr[0x1A..0x1E].try_into().unwrap());
        Ok((w, h))
    }

    /// Read one media blob's raw bytes by its decoded `<index>@` archive index —
    /// the same index `PageElement::Image`/sticky notes/PDF templates carry (and
    /// the same currency pysdocx uses), NOT a position in `media_assets`.
    pub fn media_bytes(&mut self, archive_index: usize) -> Result<Vec<u8>> {
        let pos = *self
            .media_index_map
            .get(&archive_index)
            .ok_or_else(|| Error::Format("unknown media archive index".into()))?;
        let name = self
            .media_names
            .get(pos)
            .ok_or_else(|| Error::Format("media index out of range".into()))?
            .clone();
        let mut entry = self.archive.by_name(&name)?;
        let mut data = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut data)?;
        Ok(data)
    }
}

#[cfg(test)]
mod tests {
    use super::parse_note_note;
    use crate::types::DocumentMetadata;

    #[test]
    fn parses_dark_mode_compatibility_flag() {
        let mut metadata = DocumentMetadata::default();
        let mut data = vec![0; 0x30];
        data[0x04..0x08].copy_from_slice(&0x0804_u32.to_le_bytes());

        parse_note_note(&data, &mut metadata);

        assert_eq!(metadata.dark_mode_compatibility, Some(true));

        data[0x04..0x08].copy_from_slice(&0x0004_u32.to_le_bytes());
        parse_note_note(&data, &mut metadata);

        assert_eq!(metadata.dark_mode_compatibility, Some(false));
    }

    /// The decoded `<index>@` archive index is the ONE media currency, end to end:
    /// a PDF template's `media_index` is the raw index pysdocx reports (0 = Study,
    /// 2 = Planner here) and `media_bytes(raw)` must fetch actual PDF bytes.
    /// Regression guard: the media list excludes `.spi` previews, so raw 2 is NOT
    /// position 2 — a positional fetch rendered Study (raw 0 == pos 0, luck) but
    /// left Planner blank (raw 2 was out of range of the 2-entry list).
    #[test]
    fn pdf_template_media_index_is_the_decoded_archive_index() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../samples/Notebook&Planner1_260709_213306.sdocx");
        if !path.exists() {
            eprintln!("skipping: Notebook&Planner sample not present");
            return;
        }
        let mut reader = crate::open(&path).expect("open sample");
        let mut pdf_indices = std::collections::HashSet::new();
        for i in 0..reader.page_count() {
            let page = reader.page(i).expect("parse page");
            let Some(crate::types::PageTemplate {
                source: crate::types::PageTemplateSource::CustomPdf { media_index, .. },
                ..
            }) = page.template
            else {
                panic!("page {i}: expected a PDF-backed template");
            };
            pdf_indices.insert(media_index);
            let bytes = reader.media_bytes(media_index as usize).expect("media bytes");
            assert!(bytes.starts_with(b"%PDF"), "page {i}: media {media_index} is not a PDF");
            let asset = reader.media_asset(media_index as usize).expect("media asset");
            assert!(asset.name.ends_with(".pdf"), "page {i}: {}", asset.name);
        }
        // The raw indices themselves — byte-identical to what pysdocx decodes.
        assert_eq!(pdf_indices, [0u32, 2u32].into_iter().collect());
    }
}
