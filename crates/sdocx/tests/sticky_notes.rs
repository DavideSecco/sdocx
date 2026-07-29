//! Sticky-note placement parity vs pysdocx.
//!
//! Expected values generated with pysdocx `scan_sticky_notes` (2026-07-09):
//! 3 placements across the two samples that carry sticky notes. Skips cleanly
//! when a sample is absent, like the shapes/text-box gates.

use std::path::{Path, PathBuf};

use sdocx::PageElement;

fn samples_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../samples")
}

/// (page uuid, media_index, bbox) for every sticky note in a sample.
fn sticky_rows(name: &str) -> Option<Vec<(String, usize, [f64; 4])>> {
    let path = samples_dir().join(name);
    if !path.exists() {
        eprintln!("skipping: {name} not present");
        return None;
    }
    let mut reader = sdocx::open(&path).expect("open sample");
    let mut rows = Vec::new();
    for i in 0..reader.page_count() {
        let bytes = reader.page_bytes(i).expect("page bytes");
        let page = sdocx::parse_page(&bytes).expect("parse page");
        for el in &page.elements {
            if let PageElement::StickyNote {
                bbox, media_index, ..
            } = el
            {
                rows.push((
                    page.uuid.clone(),
                    *media_index,
                    [bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max],
                ));
            }
        }
    }
    Some(rows)
}

#[test]
fn sticky_notes_match_pysdocx() {
    if let Some(rows) = sticky_rows("Allsamsungnotes_260630_113259.sdocx") {
        assert_eq!(
            rows,
            vec![(
                "73920cee-7465-11f1-b60f-9f34bf285061".to_string(),
                10,
                [156.083862, 1073.110352, 236.083862, 1153.110352],
            )]
        );
    }
    if let Some(rows) = sticky_rows("Associationpages&stickynote&images&audio_260701_183225.sdocx")
    {
        assert_eq!(
            rows,
            vec![
                (
                    "6ffea07a-7568-11f1-b6ea-df50ffd9ddce".to_string(),
                    8,
                    [25.461243, 28.565918, 105.461243, 108.565918],
                ),
                (
                    "6ffea07a-7568-11f1-b6ea-df50ffd9ddce".to_string(),
                    6,
                    [1319.644043, 1870.339844, 1399.644043, 1950.339844],
                ),
            ]
        );
    }
}

/// The decoded `skn_bg_color` ARGB int (-6482) is the default sticky yellow.
#[test]
fn sticky_bg_color_decodes() {
    let path = samples_dir().join("Allsamsungnotes_260630_113259.sdocx");
    if !path.exists() {
        eprintln!("skipping: sample not present");
        return;
    }
    let mut reader = sdocx::open(&path).expect("open sample");
    for i in 0..reader.page_count() {
        let bytes = reader.page_bytes(i).expect("page bytes");
        let page = sdocx::parse_page(&bytes).expect("parse page");
        for el in &page.elements {
            if let PageElement::StickyNote { bg_color, .. } = el {
                let c = bg_color.expect("bg color present");
                // -6482 == 0xFFFFE6AE
                assert_eq!((c.r, c.g, c.b), (0xFF, 0xE6, 0xAE));
                return;
            }
        }
    }
    panic!("no sticky note found");
}
