use clap::{Parser, ValueEnum};
use sdocx::{Document, PageTemplate, PageTemplateSource};
use sdocx_render::render_document;
use std::fs;
use std::path::PathBuf;

#[derive(Copy, Clone, Debug, PartialEq, Eq, ValueEnum)]
enum Format {
    Svg,
    Png,
}

/// Resolve the output format: explicit flag wins, else infer from the output
/// file extension, else default to SVG.
fn resolve_format(
    flag: Option<Format>,
    output: Option<&std::path::Path>,
) -> Result<Format, String> {
    if let Some(f) = flag {
        return Ok(f);
    }
    match output
        .and_then(|p| p.extension())
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .as_deref()
    {
        Some("svg") => Ok(Format::Svg),
        Some("png") => Ok(Format::Png),
        Some(other) => Err(format!(
            "unknown output extension '.{other}'; use -f/--format to set svg or png"
        )),
        None => Ok(Format::Svg),
    }
}

impl Format {
    fn ext(self) -> &'static str {
        match self {
            Format::Svg => "svg",
            Format::Png => "png",
        }
    }
}

fn svg_to_png(svg: &str) -> Result<Vec<u8>, String> {
    let mut opt = resvg::usvg::Options::default();
    // Load system fonts so <text> elements render instead of being silently dropped.
    opt.fontdb_mut().load_system_fonts();
    let tree = resvg::usvg::Tree::from_str(svg, &opt).map_err(|e| format!("invalid SVG: {e}"))?;
    let size = tree.size().to_int_size();
    let (w, h) = (size.width(), size.height());
    let mut pixmap = resvg::tiny_skia::Pixmap::new(w, h)
        .ok_or_else(|| "failed to allocate pixmap".to_string())?;
    let mut pm = pixmap.as_mut();
    resvg::render(&tree, resvg::tiny_skia::Transform::identity(), &mut pm);
    pixmap
        .encode_png()
        .map_err(|e| format!("PNG encode failed: {e}"))
}

#[derive(Parser)]
#[command(name = "sdocx", version, about = "Parse Samsung Notes .sdocx files")]
struct Cli {
    /// Path to an .sdocx file
    path: PathBuf,

    /// Output file path (format inferred from extension; defaults to the input path with a format-appropriate extension)
    #[arg(short, long)]
    output: Option<PathBuf>,

    /// Output format (overrides extension inference): svg or png
    #[arg(short, long, value_enum)]
    format: Option<Format>,
}

fn print_info(doc: &Document) {
    if let Some(dims) = doc.metadata.page_dimensions {
        eprintln!("Page dimensions: {} x {}", dims.0, dims.1);
    }
    if let Some(bg) = doc.metadata.background_color {
        eprintln!("Document background: #{:02x}{:02x}{:02x}", bg.r, bg.g, bg.b);
    }
    if let Some(enabled) = doc.metadata.dark_mode_compatibility {
        eprintln!("Dark mode compatibility: {enabled}");
    }
    eprintln!("{} page(s)", doc.pages.len());
    for (i, page) in doc.pages.iter().enumerate() {
        let total_points: usize = page.strokes.iter().map(|s| s.points.len()).sum();
        let colors: std::collections::HashSet<_> = page.strokes.iter().map(|s| s.color).collect();
        let with_pressure = page
            .strokes
            .iter()
            .filter(|s| !s.pressures.is_empty())
            .count();
        eprintln!(
            "  Page {}: {} x {}, background {}, template {}, {} strokes, {} points, {} colors, {} with pressure",
            i,
            page.width,
            page.height,
            page.background_color
                .map(|color| format!("#{:02x}{:02x}{:02x}", color.r, color.g, color.b))
                .unwrap_or_else(|| "none".to_string()),
            page.template
                .as_ref()
                .map(format_template)
                .unwrap_or_else(|| "none".to_string()),
            page.strokes.len(),
            total_points,
            colors.len(),
            with_pressure,
        );
    }
}

fn format_template(template: &PageTemplate) -> String {
    match &template.source {
        PageTemplateSource::BuiltIn => format!("built-in {}", template.id),
        PageTemplateSource::CustomPdf {
            media_index,
            page_index,
        } => {
            format!("PDF template (media {media_index}, page {})", page_index + 1)
        }
        PageTemplateSource::CustomImage { filename } => format!("image template ({filename})"),
    }
}

fn write_page(path: &std::path::Path, svg: &str, format: Format) {
    match format {
        Format::Svg => {
            if let Err(e) = fs::write(path, svg) {
                eprintln!("Error: failed to write {}: {e}", path.display());
                std::process::exit(1);
            }
            eprintln!("Wrote {} ({} bytes)", path.display(), svg.len());
        }
        Format::Png => {
            let png = svg_to_png(svg).unwrap_or_else(|e| {
                eprintln!("Error: {e}");
                std::process::exit(1);
            });
            if let Err(e) = fs::write(path, &png) {
                eprintln!("Error: failed to write {}: {e}", path.display());
                std::process::exit(1);
            }
            eprintln!("Wrote {} ({} bytes)", path.display(), png.len());
        }
    }
}

fn main() {
    let cli = Cli::parse();

    let doc = match sdocx::parse(&cli.path) {
        Ok(doc) => doc,
        Err(e) => {
            eprintln!("Error: {e}");
            std::process::exit(1);
        }
    };

    print_info(&doc);

    let format = match resolve_format(cli.format, cli.output.as_deref()) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("Error: {e}");
            std::process::exit(1);
        }
    };

    let output_base = cli
        .output
        .unwrap_or_else(|| cli.path.with_extension(format.ext()));

    let pages = render_document(&doc);

    if pages.len() == 1 {
        write_page(&output_base, &pages[0].svg, format);
    } else {
        for (i, page) in pages.iter().enumerate() {
            let stem = output_base
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy();
            let ext = output_base
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or(format.ext());
            let path = output_base.with_file_name(format!("{stem}_page{i}.{ext}"));
            write_page(&path, &page.svg, format);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{Format, resolve_format, svg_to_png};
    use std::path::Path;

    #[test]
    fn format_flag_wins_over_extension() {
        let f = resolve_format(Some(Format::Svg), Some(Path::new("out.png"))).unwrap();
        assert_eq!(f, Format::Svg);
    }

    #[test]
    fn format_inferred_from_png_extension() {
        let f = resolve_format(None, Some(Path::new("out.png"))).unwrap();
        assert_eq!(f, Format::Png);
    }

    #[test]
    fn format_inferred_from_svg_extension() {
        let f = resolve_format(None, Some(Path::new("out.svg"))).unwrap();
        assert_eq!(f, Format::Svg);
    }

    #[test]
    fn format_defaults_to_svg_when_no_output_and_no_flag() {
        let f = resolve_format(None, None).unwrap();
        assert_eq!(f, Format::Svg);
    }

    #[test]
    fn unknown_extension_without_flag_is_error() {
        assert!(resolve_format(None, Some(Path::new("out.gif"))).is_err());
    }

    #[test]
    fn extension_inference_is_case_insensitive() {
        assert_eq!(
            resolve_format(None, Some(Path::new("out.PNG"))).unwrap(),
            Format::Png
        );
        assert_eq!(
            resolve_format(None, Some(Path::new("out.Svg"))).unwrap(),
            Format::Svg
        );
    }

    #[test]
    fn svg_to_png_produces_valid_png_with_expected_size() {
        let svg = r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10" width="20" height="10"><rect x="0" y="0" width="20" height="10" fill="#252525"/><line x1="0" y1="0" x2="20" y2="10" stroke="#ffffff" stroke-width="1"/></svg>"##;
        let png = svg_to_png(svg).expect("render should succeed");
        // Full 8-byte PNG signature.
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        // IHDR width/height are big-endian u32 at byte offsets 16 and 20.
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!((w, h), (20, 10));
    }

    #[test]
    fn renders_sample_to_valid_png() {
        let doc = sdocx::parse("../../samples/handwritten.sdocx").expect("parse sample");
        let pages = sdocx_render::render_document(&doc);
        assert!(!pages.is_empty(), "sample has no pages");
        let png = svg_to_png(&pages[0].svg).expect("render sample to png");
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        assert!(
            png.len() > 100,
            "PNG should be non-trivial, got {} bytes",
            png.len()
        );
    }
}
