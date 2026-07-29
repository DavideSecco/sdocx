mod container;
mod decode;
mod error;
mod note_doc;
mod page;
pub mod samsung_spi;
mod shape;
mod types;

pub use container::Reader;
pub use error::{Error, Result};
pub use page::parse_page;
pub use types::*;

use std::fs::File;
use std::io::Cursor;
use std::path::Path;

/// Parse a `.sdocx` file from a filesystem path (reads the whole document).
pub fn parse(path: impl AsRef<Path>) -> Result<Document> {
    let file = File::open(path)?;
    container::parse_from_reader(file)
}

/// Open a `.sdocx` file lazily: metadata and page/media manifests are read now,
/// individual pages and media blobs decoded on demand. Prefer this over [`parse`]
/// for large multi-page notes. See [`Reader`].
pub fn open(path: impl AsRef<Path>) -> Result<Reader<File>> {
    Reader::open(File::open(path)?)
}

/// Parse a `.sdocx` file from in-memory bytes.
pub fn parse_bytes(bytes: &[u8]) -> Result<Document> {
    let cursor = Cursor::new(bytes);
    container::parse_from_reader(cursor)
}
