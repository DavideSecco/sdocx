//! Throwaway verification tool: `cargo run --example render_sample -- <sample.sdocx> <page> <out.png>`
//! Renders one page (Scene -> SVG -> PNG) and writes it to disk for eyeballing.
//! Not part of the shipped crate surface.

use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    let path = &args[1];
    let page_index: usize = args[2].parse().unwrap();
    let out = &args[3];

    let mut reader = sdocx::open(path).expect("open sample");
    let bytes = reader.page_bytes(page_index).expect("page bytes");
    let page = sdocx::parse_page(&bytes).expect("parse page");
    let scene = opensdocx_render::build_page_scene(&page);

    let mut media = |index: usize| -> Option<(String, Vec<u8>)> {
        let mime = reader.media_asset(index)?.mime_type.clone();
        let bytes = reader.media_bytes(index).ok()?;
        Some((mime, bytes))
    };
    let svg = opensdocx_render::render_page_svg(&scene, &mut media);
    let png = opensdocx_render::svg_to_png(&svg).expect("rasterize");
    std::fs::write(out, &png).expect("write png");
    std::fs::write(format!("{out}.svg"), &svg).expect("write svg");
    eprintln!(
        "wrote {out} ({} bytes) — {} strokes, {} shapes, {} images, {} stickies, template={:?}",
        png.len(),
        scene.strokes.len(),
        scene.shapes.len(),
        scene.images.len(),
        scene.sticky_notes.len(),
        scene.template.as_ref().map(|t| &t.kind)
    );
}
