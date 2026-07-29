//! Parity gates for the `.spi` / Maetel decoder against the native decoder.
//!
//! Three levels, cheapest first:
//!
//! 1. `chunk_boundaries_land_exactly` needs only the sample: a correct walk
//!    consumes each `AA 02` chunk to the byte, which is a ground-truth-free
//!    constraint the format gives us for free.
//! 2. `per_tile_bit_counts_match_native` compares every tile's payload bit count
//!    against the native trace captured under Unicorn -- the Rust equivalent of
//!    `spi_probe.py --verify-handlers`.
//! 3. `mode4_blocks_match_native` compares the reconstructed palette blocks
//!    against the blocks the native decoder held just before its blit.
//!
//! Inputs live in `samples/` and `apk-re/`, both private and gitignored, so
//! these skip when absent -- **loudly**, because a silent skip reading as a pass
//! is exactly how a broken port once looked green.

use std::collections::HashMap;
use std::io::Read;
use std::path::{Path, PathBuf};

use sdocx::samsung_spi::{self, SpiDecoded};

/// The `.spi` member holding the "convert to math" formula render, 1408x286.
const FORMULA_MEMBER: &str = "media/2@84bbec22-878b-11f1-ad5f-0fcae52b7cba.spi";

fn repo_path(rel: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(rel)
}

fn skip(what: &str) -> bool {
    eprintln!("SKIPPING (not a pass): {what} is absent");
    true
}

/// The formula `.spi` bytes, or `None` when the private sample is absent.
fn formula_spi() -> Option<Vec<u8>> {
    let sample = repo_path("samples/MultiMath_260724_201808/note.sdocx");
    if !sample.exists() {
        skip("samples/MultiMath_260724_201808");
        return None;
    }
    let file = std::fs::File::open(&sample).expect("open sample");
    let mut archive = zip::ZipArchive::new(file).expect("zip sample");
    let mut entry = archive.by_name(FORMULA_MEMBER).expect("formula member");
    let mut bytes = Vec::new();
    entry.read_to_end(&mut bytes).expect("read formula member");
    Some(bytes)
}

fn decode_formula() -> Option<SpiDecoded> {
    let bytes = formula_spi()?;
    Some(samsung_spi::decode_spi(&bytes).expect("decode formula .spi"))
}

/// Rows of `apk-re/fixtures/native_trace.csv`, keyed by `(plane, tile_idx)`.
fn native_trace() -> Option<HashMap<(u8, usize), (u8, usize)>> {
    let path = repo_path("apk-re/fixtures/native_trace.csv");
    if !path.exists() {
        skip("apk-re/fixtures/native_trace.csv");
        return None;
    }
    let text = std::fs::read_to_string(path).expect("read native trace");
    let mut lines = text.lines();
    let header: Vec<&str> = lines.next().expect("trace header").split(',').collect();
    let col = |name: &str| {
        header
            .iter()
            .position(|h| *h == name)
            .expect("trace column")
    };
    let (i_tile, i_plane) = (col("tile_idx"), col("plane"));
    let (i_mode, i_bits) = (col("mode"), col("payload_bits"));

    Some(
        lines
            .map(|line| {
                let f: Vec<&str> = line.split(',').collect();
                let key = (f[i_plane].parse().unwrap(), f[i_tile].parse().unwrap());
                (
                    key,
                    (f[i_mode].parse().unwrap(), f[i_bits].parse().unwrap()),
                )
            })
            .collect(),
    )
}

#[test]
fn chunk_boundaries_land_exactly() {
    let Some(bytes) = formula_spi() else { return };
    let stream = samsung_spi::parse_stream(&bytes).expect("parse stream");
    let tile_rows = usize::from(stream.info.tile_rows());
    let hint = usize::from(stream.header.tile_rows_hint);

    let chunks =
        samsung_spi::find_tile_chunks(stream.payload, tile_rows, hint).expect("locate chunks");
    let offsets: Vec<usize> = chunks.iter().map(|c| c.offset).collect();
    assert_eq!(offsets, vec![0, 13869, 32258, 46864], "AA02 chunk offsets");
    assert_eq!(stream.payload.len(), 54329, "payload length");

    // A correct walk visits every tile of every plane pass and never runs past
    // a chunk into the next one.
    let decoded = samsung_spi::decode_spi(&bytes).expect("decode");
    let tile_cols = usize::from(stream.info.tile_cols());
    let planes = usize::from(samsung_spi::plane_count_for(stream.header.color_index));
    assert_eq!(planes, 2, "the formula stream is RGB + alpha");
    assert_eq!(
        decoded.tiles.len(),
        tile_cols * tile_rows * planes,
        "walked 3168 tiles (88 x 18 x 2 planes)"
    );

    let bounds: Vec<usize> = offsets
        .iter()
        .skip(1)
        .copied()
        .chain(std::iter::once(stream.payload.len()))
        .collect();
    for (chunk, end) in chunks.iter().zip(&bounds) {
        let last = decoded
            .tiles
            .iter()
            .filter(|t| {
                let row = t.tile_index / tile_cols;
                row >= chunk.index * hint && row < chunk.index * hint + chunk.rows
            })
            .map(|t| t.payload_start_bit + t.payload_bits)
            .max()
            .expect("chunk has tiles");
        assert!(
            last.div_ceil(8) <= *end,
            "chunk {} overran its span: consumed to byte {}, expected <= {end}",
            chunk.index,
            last.div_ceil(8)
        );
        assert!(
            last.div_ceil(8) + 1 >= *end,
            "chunk {} underran its span: consumed to byte {}, expected {end}",
            chunk.index,
            last.div_ceil(8)
        );
    }
}

#[test]
fn per_tile_bit_counts_match_native() {
    let Some(decoded) = decode_formula() else {
        return;
    };
    let Some(trace) = native_trace() else { return };

    let mut checked = 0usize;
    for tile in &decoded.tiles {
        let key = (tile.plane, tile.tile_index);
        let (mode, bits) = *trace
            .get(&key)
            .unwrap_or_else(|| panic!("native trace has no plane {} tile {}", key.0, key.1));
        assert_eq!(tile.mode, mode, "plane {} tile {} mode", key.0, key.1);
        assert_eq!(
            tile.payload_bits, bits,
            "plane {} tile {} (mode {mode}) payload bits",
            key.0, key.1
        );
        checked += 1;
    }
    assert_eq!(checked, 3168, "every tile checked against the native trace");
}

#[test]
fn mode4_blocks_match_native() {
    let Some(decoded) = decode_formula() else {
        return;
    };
    let blocks_path = repo_path("apk-re/fixtures/native_blocks.bin");
    let index_path = repo_path("apk-re/fixtures/native_blocks.csv");
    if !blocks_path.exists() || !index_path.exists() {
        skip("apk-re/fixtures/native_blocks.{bin,csv}");
        return;
    }

    const TILE: usize = 16;
    const BLOCK_PIXELS: usize = TILE * TILE;
    const COMPONENTS: usize = 4;
    // Each record is 4 blocks of 256 bytes, then 4 rows of 16 context bytes.
    const STRIDE: usize = COMPONENTS * (BLOCK_PIXELS + TILE);

    let raw = std::fs::read(&blocks_path).expect("read native blocks");
    let index = std::fs::read_to_string(&index_path).expect("read block index");
    let mut lines = index.lines();
    let header: Vec<&str> = lines.next().expect("index header").split(',').collect();
    let col = |name: &str| {
        header
            .iter()
            .position(|h| *h == name)
            .expect("index column")
    };
    let (i_tile, i_plane, i_mode) = (col("tile_idx"), col("plane"), col("mode"));

    let mut native_mode4: HashMap<usize, &[u8]> = HashMap::new();
    for (position, line) in lines.enumerate() {
        let f: Vec<&str> = line.split(',').collect();
        if f[i_plane] != "0" || f[i_mode] != "4" {
            continue;
        }
        let start = position * STRIDE;
        native_mode4.insert(
            f[i_tile].parse().expect("tile idx"),
            &raw[start..start + 3 * BLOCK_PIXELS],
        );
    }
    assert_eq!(
        native_mode4.len(),
        313,
        "mode 4 tiles in the native fixture"
    );

    let mut checked = 0usize;
    for tile in decoded.tiles.iter().filter(|t| t.plane == 0 && t.mode == 4) {
        let native = native_mode4
            .get(&tile.tile_index)
            .unwrap_or_else(|| panic!("native mode 4 tile {}", tile.tile_index));
        let mine = decoded
            .blocks
            .get(&(0, tile.tile_index))
            .expect("decoded blocks");
        assert_eq!(
            &mine[..3 * BLOCK_PIXELS],
            *native,
            "tile {} palette blocks",
            tile.tile_index
        );
        checked += 1;
    }
    assert_eq!(checked, 313, "every mode 4 tile reconstructed exactly");
}
