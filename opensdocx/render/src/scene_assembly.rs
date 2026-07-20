//! Reads a `sdocx::Reader` and assembles a page's full `PageScene` — the
//! parts of scene-building that need the archive (typed-note pagination
//! anchor, structural tables, inline images), on top of `build_page_scene`'s
//! pure `sdocx::Page -> PageScene`. Shared by the Tauri `export_page`/
//! `get_page_scene` commands and `opensdocx-cli`, so both entry points
//! build the exact same scene for a given page instead of two independent
//! (and easily divergent) implementations.

use crate::{
    build_page_scene, build_scene_table, build_scene_text, PageScene, SceneImage, ScenePaginate,
};

/// Pysdocx places document-level typed text on the first otherwise-empty page,
/// excluding pages occupied by a structural table. Keep opening lazy by using
/// ZIP member sizes: corpus-empty `.page` members are 336–340 bytes, whereas a
/// serialized page object makes the member much larger. This is a placement
/// heuristic, not a decoded note→page reference.
pub fn find_typed_text_anchor(
    reader: &mut sdocx::Reader<std::fs::File>,
) -> Result<Option<usize>, String> {
    if reader.metadata().note_text.is_none() {
        return Ok(None);
    }
    let table_pages: Vec<usize> = reader
        .metadata()
        .note_tables
        .iter()
        .map(sdocx::NoteTable::page_index)
        .collect();
    for index in 0..reader.page_count() {
        if table_pages.contains(&index) {
            continue;
        }
        if reader.page_uncompressed_size(index).map_err(|e| e.to_string())? <= 512 {
            return Ok(Some(index));
        }
    }
    Ok(Some(0))
}

/// Everything about a page that must be read from the `Reader` before it can
/// be assembled into a `PageScene` — split out so a caller can gather this
/// (which needs `&mut Reader`, e.g. behind a lock) separately from
/// `assemble_page_scene` (pure, no `Reader` access).
pub type PageInputs = (
    Vec<u8>,
    Option<sdocx::RichTextBox>,
    Option<(usize, f64)>,
    Vec<sdocx::NoteTable>,
    Vec<SceneImage>,
);

pub fn gather_page_inputs(
    reader: &mut sdocx::Reader<std::fs::File>,
    typed_text_anchor: Option<usize>,
    index: usize,
) -> Result<PageInputs, String> {
    let bytes = reader.page_bytes(index).map_err(|e| e.to_string())?;
    // The typed note body is a document-level flow anchored on the first
    // otherwise-empty page. It is attached to EVERY page and split into
    // page-height bands by the worker (pysdocx `paginate_typed_text`), so
    // overflow flows onto later pages instead of running off the bottom of
    // page 0. Bands use the anchor page's height uniformly.
    let pagination = typed_text_anchor
        .filter(|&anchor| index >= anchor)
        .map(|anchor| {
            reader
                .page_size(anchor)
                .map(|(_, height)| (index - anchor, height as f64))
        })
        .transpose()
        .map_err(|e| e.to_string())?;
    let note_text = pagination
        .as_ref()
        .and_then(|_| reader.metadata().note_text.clone());
    // Byte-exact structural tables carry their own 0-based host page
    // (`NoteTable::page_index`, note.note's table→page reference), so each
    // goes on exactly its page — no placement guess.
    let meta = reader.metadata();
    let tables: Vec<sdocx::NoteTable> = meta
        .note_tables
        .iter()
        .filter(|t| t.page_index() == index)
        .cloned()
        .collect();
    // Inline images live in note.note (not a page object tree); each resolves
    // to a host page (section→page heuristic) + a page-local bbox.
    let inline_images: Vec<SceneImage> = meta
        .note_inline_images
        .iter()
        .filter(|im| im.page_index == index)
        .map(|im| SceneImage {
            x: im.bbox.x_min,
            y: im.bbox.y_min,
            w: im.bbox.x_max - im.bbox.x_min,
            h: im.bbox.y_max - im.bbox.y_min,
            media_index: im.media_index,
            angle_deg: None,
            affine: None,
            crop: im.crop.map(|c| [c.x, c.y, c.w, c.h]),
        })
        .collect();
    Ok((bytes, note_text, pagination, tables, inline_images))
}

/// Assembles the final `PageScene` from `gather_page_inputs`' output — pure,
/// no `Reader` access, so it runs outside the reader lock.
pub fn assemble_page_scene(inputs: PageInputs) -> Result<PageScene, String> {
    let (bytes, note_text, pagination, tables, inline_images) = inputs;
    // Media indices in the parsed page are the decoded `<index>@` archive indices
    // (the parser's one media currency, same as pysdocx); `get_media` resolves them.
    let page = sdocx::parse_page(&bytes).map_err(|e| e.to_string())?;
    let mut scene = build_page_scene(&page);
    scene.images.extend(inline_images);
    if let (Some(text), Some((slot, band_height))) = (note_text, pagination) {
        let mut st = build_scene_text(&text, page.width as f64);
        st.paginate = Some(ScenePaginate { slot, band_height });
        scene.texts.push(st);
    }
    scene.tables = tables.iter().map(build_scene_table).collect();
    Ok(scene)
}

/// Convenience wrapper over `gather_page_inputs` + `assemble_page_scene` for
/// callers (like `opensdocx-cli`) that don't need to split reader access
/// from scene assembly across a lock, the way the Tauri commands do.
pub fn build_full_page_scene(
    reader: &mut sdocx::Reader<std::fs::File>,
    typed_text_anchor: Option<usize>,
    index: usize,
) -> Result<PageScene, String> {
    let inputs = gather_page_inputs(reader, typed_text_anchor, index)?;
    assemble_page_scene(inputs)
}
