"""Measure Samsung Notes typed-text ground truth against the current layout model.

This is a render-calibration tool, not a format decoder.  It consumes full-page
Samsung Notes screenshots, detects horizontal ink bands, maps their centres to
the decoded page coordinate system, and aligns them in order with the lines
produced by :func:`pysdocx.render.paginate_typed_text`.

The detected centre is deliberately called an ``ink_center`` rather than a
baseline: a raster screenshot alone does not identify the font baseline
without knowing Samsung's exact font metrics.  Line-to-line deltas and residual
trends remain useful and do not depend on that distinction.

Example (the two existing plain-background GT pages)::

    MPLCONFIGDIR=/tmp/matplotlib .venv/bin/python \
      -m pysdocx.measure_typed_text_gt \
      samples/OnlyTextTypeWritten_260701_180427/note.sdocx \
      samples/OnlyTextTypeWritten_260701_180427/gt/photo_2026-07-01_18-06-27.jpg \
      samples/OnlyTextTypeWritten_260701_180427/gt/photo_2026-07-01_18-06-58.jpg

With one PDF argument, the tool instead reads vector text boxes through
``pdftotext -bbox-layout`` and compares page assignment plus ink centres.  The
raster detector is intentionally small and inspectable.  Its defaults are
pinned to the lossless/full-page 905x1280 Samsung screenshots in the current
corpus; thresholds can be overridden for future captures.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

from pysdocx.container import list_pages, load_note, load_page
from pysdocx.note import parse_typed_text
from pysdocx.page import parse_page
from pysdocx.render import (
    DEFAULT_INK,
    TYPED_TEXT_BLANK_H,
    TYPED_TEXT_FONTPT,
    TYPED_TEXT_LINE_H,
    TYPED_TEXT_X0,
    TYPED_TEXT_Y0,
    _render_rich_text,
    paginate_typed_text,
)


@dataclass(frozen=True)
class InkBand:
    top_px: int
    bottom_px: int
    center_px: float
    height_px: int
    peak_pixels: int


@dataclass(frozen=True)
class LineMeasurement:
    page: int
    line: int
    text: str
    continuous_y: float
    advance: float
    predicted_y: float
    ink_center_y: float
    residual: float
    ink_top_y: float
    ink_bottom_y: float
    ink_height_y: float


def detect_horizontal_ink_bands(
    image_path: Path,
    *,
    x_margin: int = 30,
    luminance_threshold: float = 180.0,
    min_row_pixels: int = 4,
    min_peak_pixels: int = 25,
    merge_gap: int = 5,
) -> tuple[list[InkBand], int, int]:
    """Return horizontal dark-ink bands plus image ``(width, height)``.

    The peak filter rejects JPEG/grid residue.  The small-gap merge joins
    underline/strikethrough strokes back to their glyph band.  Background grid
    lines are lighter than the default luminance threshold in the existing GT.
    """

    rgb = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.float32)
    height, width, _ = rgb.shape
    if width <= 2 * x_margin:
        raise ValueError(f"image too narrow for x-margin {x_margin}: {image_path}")

    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    row_profile = (luminance[:, x_margin : width - x_margin] < luminance_threshold).sum(axis=1)
    dark_rows = np.flatnonzero(row_profile >= min_row_pixels)
    if dark_rows.size == 0:
        return [], width, height

    split_at = np.where(np.diff(dark_rows) > 1)[0] + 1
    raw_groups = np.split(dark_rows, split_at)
    groups: list[tuple[int, int, int]] = []
    for group in raw_groups:
        if group.size < 2:
            continue
        peak = int(row_profile[group].max())
        if peak < min_peak_pixels:
            continue
        top, bottom = int(group[0]), int(group[-1])
        if groups and top - groups[-1][1] <= merge_gap:
            old_top, _old_bottom, old_peak = groups[-1]
            groups[-1] = (old_top, bottom, max(old_peak, peak))
        else:
            groups.append((top, bottom, peak))

    bands = [
        InkBand(
            top_px=top,
            bottom_px=bottom,
            center_px=(top + bottom) / 2.0,
            height_px=bottom - top + 1,
            peak_pixels=peak,
        )
        for top, bottom, peak in groups
    ]
    return bands, width, height


def _page_geometry(sample: Path) -> tuple[int, int]:
    page_names = list_pages(sample)
    if not page_names:
        raise ValueError(f"sample contains no .page members: {sample}")
    _name, page_data = load_page(sample, page_names[0])
    page = parse_page(page_data)
    return int(page["width"]), int(page["height"])


def _predicted_layout(
    sample: Path, page_width: int, page_height: int
) -> tuple[list[list[dict]], list[dict]]:
    note = load_note(sample)
    if note is None:
        raise ValueError(f"sample contains no note.note: {sample}")
    typed = parse_typed_text(note)
    if typed is None:
        raise ValueError(f"sample contains no document-level typed text: {sample}")
    pages = paginate_typed_text(typed, page_width, page_height, (9, 12))

    # Keep the continuous coordinates and advances that paginate_typed_text's
    # public result intentionally strips. They explain each page break in the
    # report without changing renderer behaviour.
    fig, ax = plt.subplots(figsize=(9, 12))
    try:
        ax.set_xlim(0, page_width)
        ax.set_ylim(page_height, 0)
        sink: list = []
        _render_rich_text(
            ax,
            typed,
            x0=TYPED_TEXT_X0,
            y0=TYPED_TEXT_Y0,
            max_width=page_width - TYPED_TEXT_X0,
            line_h=TYPED_TEXT_LINE_H,
            blank_h=TYPED_TEXT_BLANK_H,
            fontpt=TYPED_TEXT_FONTPT,
            default_ink=DEFAULT_INK,
            sink=sink,
            typed_note_model=True,
        )
    finally:
        plt.close(fig)

    by_y: dict[float, dict] = {}
    continuous: list[dict] = []
    for _x, y, segment, _style, advance in sink:
        key = round(float(y), 2)
        line = by_y.get(key)
        if line is None:
            line = {"y": float(y), "advance": float(advance), "segments": []}
            by_y[key] = line
            continuous.append(line)
        line["advance"] = max(line["advance"], float(advance))
        line["segments"].append(segment)
    continuous.sort(key=lambda line: line["y"])
    if sum(map(len, pages)) != len(continuous):
        raise ValueError("continuous and paginated layout line counts disagree")
    return pages, continuous


def measure_ground_truth(
    sample: Path,
    images: list[Path],
    *,
    x_margin: int = 30,
    luminance_threshold: float = 180.0,
    min_row_pixels: int = 4,
    min_peak_pixels: int = 25,
    merge_gap: int = 5,
) -> dict:
    page_width, page_height = _page_geometry(sample)
    predicted_pages, continuous_lines = _predicted_layout(sample, page_width, page_height)
    if len(images) > len(predicted_pages):
        raise ValueError(
            f"got {len(images)} GT images but the current model has only "
            f"{len(predicted_pages)} non-empty typed-text pages"
        )

    measurements: list[LineMeasurement] = []
    pages: list[dict] = []
    continuous_index = 0
    for page_index, image_path in enumerate(images):
        predicted = predicted_pages[page_index]
        bands, image_width, image_height = detect_horizontal_ink_bands(
            image_path,
            x_margin=x_margin,
            luminance_threshold=luminance_threshold,
            min_row_pixels=min_row_pixels,
            min_peak_pixels=min_peak_pixels,
            merge_gap=merge_gap,
        )
        expected_count = len(predicted)
        if len(bands) < expected_count:
            raise ValueError(
                f"page {page_index + 1}: detected {len(bands)} bands but expected "
                f"{expected_count}; adjust detector thresholds"
            )

        # Typed note-body text is above the in-page text boxes in the existing
        # page-2 GT.  Taking the first expected bands makes that explicit and we
        # report the unused count so an unexpected ordering cannot stay hidden.
        used_bands = bands[:expected_count]
        scale_y = page_height / image_height
        page_measurements: list[LineMeasurement] = []
        page_continuous = continuous_lines[continuous_index : continuous_index + expected_count]
        if page_index == 0:
            break_lead_gap = 0.0
        else:
            previous = continuous_lines[continuous_index - 1]
            first = page_continuous[0]
            break_lead_gap = max(
                0.0, float(first["y"]) - (float(previous["y"]) + float(previous["advance"]))
            )
        for line_index, (line, band) in enumerate(zip(predicted, used_bands), 1):
            continuous = page_continuous[line_index - 1]
            predicted_y = float(line["y"])
            ink_center_y = band.center_px * scale_y
            top_y = band.top_px * scale_y
            bottom_y = band.bottom_px * scale_y
            measurement = LineMeasurement(
                page=page_index + 1,
                line=line_index,
                text="".join(segment[1] for segment in line["segs"]),
                continuous_y=float(continuous["y"]),
                advance=float(continuous["advance"]),
                predicted_y=predicted_y,
                ink_center_y=ink_center_y,
                residual=ink_center_y - predicted_y,
                ink_top_y=top_y,
                ink_bottom_y=bottom_y,
                ink_height_y=bottom_y - top_y,
            )
            measurements.append(measurement)
            page_measurements.append(measurement)

        residuals = np.array([m.residual for m in page_measurements], dtype=float)
        pages.append(
            {
                "page": page_index + 1,
                "image": str(image_path),
                "image_size": [image_width, image_height],
                "scale_y": scale_y,
                "expected_lines": expected_count,
                "detected_bands": len(bands),
                "unused_bands": len(bands) - expected_count,
                "break_lead_gap": break_lead_gap,
                "mean_residual": float(residuals.mean()),
                "rmse": float(math.sqrt(np.mean(residuals**2))),
                "max_abs_residual": float(np.abs(residuals).max()),
            }
        )
        continuous_index += expected_count

    all_residuals = np.array([m.residual for m in measurements], dtype=float)
    return {
        "sample": str(sample),
        "page_size": [page_width, page_height],
        "detector": {
            "x_margin": x_margin,
            "luminance_threshold": luminance_threshold,
            "min_row_pixels": min_row_pixels,
            "min_peak_pixels": min_peak_pixels,
            "merge_gap": merge_gap,
        },
        "pages": pages,
        "summary": {
            "lines": len(measurements),
            "mean_residual": float(all_residuals.mean()),
            "rmse": float(math.sqrt(np.mean(all_residuals**2))),
            "max_abs_residual": float(np.abs(all_residuals).max()),
        },
        "measurements": [asdict(m) for m in measurements],
    }


def _pdf_text_lines(pdf: Path) -> tuple[list[dict], list[tuple[float, float]]]:
    """Extract vector text line boxes with Poppler's ``pdftotext -bbox-layout``."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-bbox-layout", str(pdf), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("PDF GT measurement requires the `pdftotext` executable") from exc
    root = ET.fromstring(proc.stdout)
    pages = [node for node in root.iter() if node.tag.endswith("page")]
    sizes: list[tuple[float, float]] = []
    lines: list[dict] = []
    for page_index, page in enumerate(pages, 1):
        sizes.append((float(page.attrib["width"]), float(page.attrib["height"])))
        page_line = 0
        for node in page.iter():
            if not node.tag.endswith("line"):
                continue
            page_line += 1
            words = ["".join(word.itertext()) for word in node if word.tag.endswith("word")]
            lines.append(
                {
                    "page": page_index,
                    "line": page_line,
                    "text": " ".join(words),
                    "y_min": float(node.attrib["yMin"]),
                    "y_max": float(node.attrib["yMax"]),
                }
            )
    return lines, sizes


def measure_pdf_ground_truth(sample: Path, pdf: Path) -> dict:
    """Compare vector Samsung-PDF text coordinates and page breaks to pysdocx."""
    page_width, page_height = _page_geometry(sample)
    predicted_pages, continuous = _predicted_layout(sample, page_width, page_height)
    observed, pdf_sizes = _pdf_text_lines(pdf)
    predicted = [
        {
            "page": page_index,
            "line": line_index,
            "y": float(line["y"]),
            "text": "".join(segment[1] for segment in line["segs"]),
        }
        for page_index, page in enumerate(predicted_pages, 1)
        for line_index, line in enumerate(page, 1)
    ]
    if len(predicted) != len(observed):
        # A document PDF can contain vector text unrelated to the note body
        # (notably structural table cells). Keep only the ordered multiset of
        # body lines; PDF export omits bullet/checkbox marker glyphs, so compare
        # after stripping list prefixes.
        def body_key(text: str) -> str:
            return re.sub(r"^(?:\d+\.\s*|[•☐☑]\s*)", "", text).strip()

        remaining = Counter(body_key(row["text"]) for row in predicted)
        body_observed = []
        for row in observed:
            key = body_key(row["text"])
            if remaining[key] > 0:
                body_observed.append(row)
                remaining[key] -= 1
        if not any(remaining.values()):
            observed = body_observed
    if len(predicted) != len(observed):
        raise ValueError(
            f"PDF has {len(observed)} vector text lines, current model has {len(predicted)}"
        )

    first_observed_page = min(row["page"] for row in observed)
    rows = []
    for index, (want, got, flow) in enumerate(zip(predicted, observed, continuous), 1):
        pdf_width, _pdf_height = pdf_sizes[got["page"] - 1]
        # Samsung's PDF text transform is uniform: native page width 1600 ->
        # PDF width 600. Using the width scale preserves the exact font/pitch
        # ratios (the PDF MediaBox height differs from .page by ~0.15%).
        scale = page_width / pdf_width
        observed_center = (got["y_min"] + got["y_max"]) / 2.0 * scale
        relative_pdf_page = got["page"] - first_observed_page + 1
        same_page = want["page"] == relative_pdf_page
        rows.append(
            {
                "index": index,
                "text": got["text"],
                "predicted_page": want["page"],
                "pdf_page": relative_pdf_page,
                "pdf_document_page": got["page"],
                "predicted_y": want["y"],
                "pdf_ink_center_y": observed_center,
                "residual": observed_center - want["y"] if same_page else None,
                "continuous_y": float(flow["y"]),
                "advance": float(flow["advance"]),
            }
        )

    residuals = np.array([row["residual"] for row in rows if row["residual"] is not None])
    page_matches = sum(row["predicted_page"] == row["pdf_page"] for row in rows)
    return {
        "sample": str(sample),
        "pdf": str(pdf),
        "page_size": [page_width, page_height],
        "pdf_page_sizes": [list(size) for size in pdf_sizes],
        "predicted_page_line_counts": [len(page) for page in predicted_pages],
        "pdf_page_line_counts": [sum(row["page"] == p for row in observed) for p in range(1, len(pdf_sizes) + 1)],
        "summary": {
            "lines": len(rows),
            "page_matches": page_matches,
            "page_mismatches": len(rows) - page_matches,
            "mean_residual_same_page": float(residuals.mean()) if residuals.size else None,
            "rmse_same_page": float(math.sqrt(np.mean(residuals**2))) if residuals.size else None,
            "max_abs_residual_same_page": float(np.abs(residuals).max()) if residuals.size else None,
        },
        "measurements": rows,
    }


def _markdown_report(result: dict) -> str:
    out = [
        "# Typed-text GT measurement",
        "",
        f"Sample: `{result['sample']}`  ",
        f"Page size: `{result['page_size'][0]}x{result['page_size'][1]}`",
        "",
        "The observed coordinate is the centre of the raster ink band, not a proven font baseline.",
        "Positive residual means Samsung renders the line lower than the current model.",
        "",
        "The break gap is the continuous inter-line gap retained before a bumped first row.",
        "",
        "| page | lines | detected | unused | break gap | mean residual | RMSE | max abs |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for page in result["pages"]:
        out.append(
            f"| {page['page']} | {page['expected_lines']} | {page['detected_bands']} | "
            f"{page['unused_bands']} | {page['break_lead_gap']:.2f} | "
            f"{page['mean_residual']:.2f} | {page['rmse']:.2f} | "
            f"{page['max_abs_residual']:.2f} |"
        )
    out.extend(
        [
            "",
            "| page | line | predicted y | ink centre y | residual | ink height | text |",
            "|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in result["measurements"]:
        text = row["text"].replace("|", "\\|")
        out.append(
            f"| {row['page']} | {row['line']} | {row['predicted_y']:.2f} | "
            f"{row['ink_center_y']:.2f} | {row['residual']:+.2f} | "
            f"{row['ink_height_y']:.2f} | {text} |"
        )
    return "\n".join(out)


def _pdf_markdown_report(result: dict) -> str:
    summary = result["summary"]
    out = [
        "# Typed-text vector-PDF GT measurement",
        "",
        f"Sample: `{result['sample']}`  ",
        f"PDF: `{result['pdf']}`  ",
        f"Predicted page rows: `{result['predicted_page_line_counts']}`  ",
        f"PDF page rows: `{result['pdf_page_line_counts']}`",
        "",
        f"Page matches: **{summary['page_matches']}/{summary['lines']}**; "
        f"RMSE on same-page ink centres: **{summary['rmse_same_page']:.2f}** page units.",
        "",
        "| # | predicted page | PDF page | predicted y | PDF ink centre y | residual | advance | text |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["measurements"]:
        residual = "page mismatch" if row["residual"] is None else f"{row['residual']:+.2f}"
        text = row["text"].replace("|", "\\|")
        out.append(
            f"| {row['index']} | {row['predicted_page']} | {row['pdf_page']} | "
            f"{row['predicted_y']:.2f} | {row['pdf_ink_center_y']:.2f} | "
            f"{residual} | {row['advance']:.2f} | {text} |"
        )
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path, help="source .sdocx")
    parser.add_argument(
        "ground_truth",
        type=Path,
        nargs="+",
        help="one Samsung vector PDF or ordered full-page Samsung GT images",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    parser.add_argument("--x-margin", type=int, default=30)
    parser.add_argument("--luminance-threshold", type=float, default=180.0)
    parser.add_argument("--min-row-pixels", type=int, default=4)
    parser.add_argument("--min-peak-pixels", type=int, default=25)
    parser.add_argument("--merge-gap", type=int, default=5)
    args = parser.parse_args()

    is_pdf = len(args.ground_truth) == 1 and args.ground_truth[0].suffix.lower() == ".pdf"
    if is_pdf:
        result = measure_pdf_ground_truth(args.sample, args.ground_truth[0])
    else:
        result = measure_ground_truth(
            args.sample,
            args.ground_truth,
            x_margin=args.x_margin,
            luminance_threshold=args.luminance_threshold,
            min_row_pixels=args.min_row_pixels,
            min_peak_pixels=args.min_peak_pixels,
            merge_gap=args.merge_gap,
        )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(_pdf_markdown_report(result) if is_pdf else _markdown_report(result))


if __name__ == "__main__":
    main()
