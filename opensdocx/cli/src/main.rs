//! `opensdocx-cli` — command-line export for `.sdocx` files, sharing the
//! exact same `opensdocx-render` functions the Tauri app's export button
//! calls (see `opensdocx/src-tauri/src/lib.rs::export_page`), so a file
//! exported from the terminal matches one exported from the app for the
//! same page.
//!
//! Rich text and tables are not yet drawn by `opensdocx-render` (see its
//! `svg` module docs) — exported pages currently omit them.

use clap::{Parser, Subcommand, ValueEnum};
use std::path::{Path, PathBuf};

#[derive(Parser)]
#[command(name = "opensdocx-cli", version, about = "Command-line tools for .sdocx files")]
struct Cli {
    /// Path to an .sdocx file
    path: PathBuf,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Render page(s) to an image/vector format
    Export {
        /// Output format
        format: Format,

        /// Output path. For a single `--page`, the exact file to write
        /// (defaults to `<input-stem>.<ext>`). Without `--page`, every page
        /// is written next to this path with a `_page{N}` suffix (defaults
        /// to `<input-stem>_page{N}.<ext>` in the input's directory).
        #[arg(short, long)]
        output: Option<PathBuf>,

        /// Export only this 0-based page instead of every page
        #[arg(short, long)]
        page: Option<usize>,
    },
}

#[derive(Clone, Copy, ValueEnum)]
enum Format {
    Svg,
    Png,
}

impl Format {
    fn ext(self) -> &'static str {
        match self {
            Format::Svg => "svg",
            Format::Png => "png",
        }
    }
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("Error: {msg}");
    std::process::exit(1);
}

/// Renders one page and writes it to `path`, in the requested format —
/// the same two `opensdocx-render` calls `export_page` makes in the Tauri
/// backend.
fn export_one(reader: &mut sdocx::Reader<std::fs::File>, index: usize, format: Format, path: &Path) {
    let bytes = reader
        .page_bytes(index)
        .unwrap_or_else(|e| die(format!("page {index}: {e}")));
    let page = sdocx::parse_page(&bytes).unwrap_or_else(|e| die(format!("page {index}: {e}")));
    let scene = opensdocx_render::build_page_scene(&page);
    let mut media = |media_index: usize| -> Option<(String, Vec<u8>)> {
        let mime = reader.media_asset(media_index)?.mime_type.clone();
        let bytes = reader.media_bytes(media_index).ok()?;
        Some((mime, bytes))
    };
    let svg = opensdocx_render::render_page_svg(&scene, &mut media);
    let bytes = match format {
        Format::Svg => svg.into_bytes(),
        Format::Png => opensdocx_render::svg_to_png(&svg).unwrap_or_else(|e| die(e)),
    };
    std::fs::write(path, &bytes).unwrap_or_else(|e| die(format!("write {}: {e}", path.display())));
    eprintln!("Wrote {} ({} bytes)", path.display(), bytes.len());
}

fn main() {
    let cli = Cli::parse();
    let mut reader = sdocx::open(&cli.path).unwrap_or_else(|e| die(e));

    let Command::Export { format, output, page } = cli.command;
    let stem = cli.path.file_stem().unwrap_or_default().to_string_lossy().into_owned();
    let dir = output
        .as_deref()
        .and_then(Path::parent)
        .filter(|p| !p.as_os_str().is_empty())
        .map(Path::to_path_buf)
        .or_else(|| cli.path.parent().map(Path::to_path_buf))
        .unwrap_or_default();

    if let Some(index) = page {
        let path = output.unwrap_or_else(|| dir.join(format!("{stem}.{}", format.ext())));
        export_one(&mut reader, index, format, &path);
    } else {
        let n = reader.page_count();
        for index in 0..n {
            let path = dir.join(format!("{stem}_page{index}.{}", format.ext()));
            export_one(&mut reader, index, format, &path);
        }
    }
}
