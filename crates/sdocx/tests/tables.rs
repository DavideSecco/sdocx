//! Table-parser parity gate vs pysdocx.
//!
//! Expected values generated with pysdocx `parse_tables` (2026-07-09,
//! `tests/fixtures/tables_pysdocx.json`): 2 notes carry a table (4×3 with 12
//! cells and 2×3 with 6 cells). The fixture is small, so the load here is a
//! spot-check against hardcoded totals + a full-field check of representative
//! cells; the numeric fixture stays committed for regeneration/diffing.
//! Skips cleanly when a sample is absent, like the other gates.

use std::path::{Path, PathBuf};

fn samples_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../samples")
}

fn tables_of(name: &str) -> Option<Vec<sdocx::Table>> {
    let path = samples_dir().join(name);
    if !path.exists() {
        eprintln!("skipping: {name} not present");
        return None;
    }
    let reader = sdocx::open(&path).expect("open sample");
    Some(reader.metadata().tables.clone())
}

#[test]
fn tables_match_pysdocx() {
    if let Some(tables) = tables_of("Allsamsungnotes_260630_113259.sdocx") {
        assert_eq!(tables.len(), 1);
        let t = &tables[0];
        assert_eq!((t.rows, t.cols, t.cells.len()), (4, 3, 12));
        let bbox = t.bbox.expect("bbox");
        assert!((bbox.x_min - 72.11111450195312).abs() < 1e-9);
        assert!((bbox.y_min - 1322.3344319661458).abs() < 1e-9);
        assert!((bbox.x_max - 1528.1111907958984).abs() < 1e-9);
        assert!((bbox.y_max - 1824.5567626953125).abs() < 1e-9);
        assert_eq!(t.x_edges.len(), 4);
        assert_eq!(t.y_edges.len(), 5);

        let c = &t.cells[0];
        assert_eq!((c.text.as_str(), c.row, c.col), ("Cell1,1", 0, 0));
        assert!((c.anchor.x - 72.11111450195312).abs() < 1e-9);
        assert!((c.anchor.y - 1447.8900146484375).abs() < 1e-9);
        assert!(!c.bold && !c.italic && !c.underline);
        let col = c.color.expect("default color run present");
        assert_eq!((col.r, col.g, col.b), (37, 37, 37));
        assert_eq!(c.font_size, Some(15.0));

        // Row-major order: last cell is row 3, col 2.
        let last = t.cells.last().unwrap();
        assert_eq!((last.row, last.col), (3, 2));
    }

    if let Some(tables) = tables_of("Associationpages&stickynote&images&audio_260701_183225.sdocx")
    {
        assert_eq!(tables.len(), 1);
        let t = &tables[0];
        assert_eq!((t.rows, t.cols, t.cells.len()), (2, 3, 6));

        // The bold auto-shrunk cell keeps its own font size and style.
        let styled = t
            .cells
            .iter()
            .find(|c| c.text == "c12ingrassettoepiccolo")
            .expect("styled cell");
        assert!(styled.bold && !styled.italic && !styled.underline);
        assert_eq!(styled.font_size, Some(4.0));
        assert_eq!((styled.row, styled.col), (0, 1));
    }
}
