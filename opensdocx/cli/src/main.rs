//! `opensdocx-cli` — command-line export for `.sdocx` files, sharing the
//! exact same `opensdocx-render` functions the Tauri app's export button
//! calls (see `opensdocx/src-tauri/src/lib.rs::export_page`) — including
//! scene assembly (`opensdocx_render::build_full_page_scene`, which wires in
//! structural tables, the typed-note pagination band, and inline images,
//! not just `build_page_scene`'s page-local elements), so a file exported
//! from the terminal matches one exported from the app for the same page.

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
        /// (defaults to `<input-stem>.<ext>`). Without `--page`, SVG/PNG
        /// write one file per page next to this path with a `_page{N}`
        /// suffix (defaults to `<input-stem>_page{N}.<ext>`); PDF instead
        /// always writes ONE multi-page file (defaults to `<input-stem>.pdf`)
        /// — PDF's natural unit is the whole document, not a single page.
        #[arg(short, long)]
        output: Option<PathBuf>,

        /// Export only this 0-based page instead of every page
        #[arg(short, long)]
        page: Option<usize>,
    },
}

#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Format {
    Svg,
    Png,
    Pdf,
}

impl Format {
    fn ext(self) -> &'static str {
        match self {
            Format::Svg => "svg",
            Format::Png => "png",
            Format::Pdf => "pdf",
        }
    }
}

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("Error: {msg}");
    std::process::exit(1);
}

/// Renders one page and writes it to `path`, in the requested format — the
/// same scene-assembly + `opensdocx-render` draw calls `export_page` makes
/// in the Tauri backend.
fn export_one(
    reader: &mut sdocx::Reader<std::fs::File>,
    typed_text_anchor: Option<usize>,
    index: usize,
    format: Format,
    path: &Path,
) {
    let scene = opensdocx_render::build_full_page_scene(reader, typed_text_anchor, index)
        .unwrap_or_else(|e| die(format!("page {index}: {e}")));
    let mut media = |media_index: usize| -> Option<(String, Vec<u8>)> {
        let mime = reader.media_asset(media_index)?.mime_type.clone();
        let bytes = reader.media_bytes(media_index).ok()?;
        Some((mime, bytes))
    };
    let svg = opensdocx_render::render_page_svg(&scene, &mut media);
    let bytes = match format {
        Format::Svg => svg.into_bytes(),
        Format::Png => opensdocx_render::svg_to_png(&svg).unwrap_or_else(|e| die(e)),
        // A single-page PDF is just a 1-element multi-page document — same
        // function the whole-document (no `--page`) branch in main() uses.
        Format::Pdf => opensdocx_render::render_document_pdf(&[svg]).unwrap_or_else(|e| die(e)),
    };
    std::fs::write(path, &bytes).unwrap_or_else(|e| die(format!("write {}: {e}", path.display())));
    eprintln!("Wrote {} ({} bytes)", path.display(), bytes.len());
}

fn main() {
    let cli = Cli::parse();
    let mut reader = sdocx::open(&cli.path).unwrap_or_else(|e| die(e));
    let typed_text_anchor =
        opensdocx_render::find_typed_text_anchor(&mut reader).unwrap_or_else(|e| die(e));

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
        export_one(&mut reader, typed_text_anchor, index, format, &path);
    } else if format == Format::Pdf {
        // PDF's natural unit is the whole document: one multi-page file,
        // not one file per page like SVG/PNG below.
        let n = reader.page_count();
        let mut svgs = Vec::with_capacity(n);
        for index in 0..n {
            let scene = opensdocx_render::build_full_page_scene(&mut reader, typed_text_anchor, index)
                .unwrap_or_else(|e| die(format!("page {index}: {e}")));
            let mut media = |media_index: usize| -> Option<(String, Vec<u8>)> {
                let mime = reader.media_asset(media_index)?.mime_type.clone();
                let bytes = reader.media_bytes(media_index).ok()?;
                Some((mime, bytes))
            };
            svgs.push(opensdocx_render::render_page_svg(&scene, &mut media));
        }
        let pdf = opensdocx_render::render_document_pdf(&svgs).unwrap_or_else(|e| die(e));
        let path = output.unwrap_or_else(|| dir.join(format!("{stem}.pdf")));
        std::fs::write(&path, &pdf).unwrap_or_else(|e| die(format!("write {}: {e}", path.display())));
        eprintln!("Wrote {} ({} bytes, {} pages)", path.display(), pdf.len(), n);
    } else {
        let n = reader.page_count();
        for index in 0..n {
            let path = dir.join(format!("{stem}_page{index}.{}", format.ext()));
            export_one(&mut reader, typed_text_anchor, index, format, &path);
        }
    }
}
