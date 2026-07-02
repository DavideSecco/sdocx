"""CLI entry point: python -m pysdocx <command> ..."""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pysdocx.container import list_pages, load_page
from pysdocx.dump import dump_container
from pysdocx.ink import color_hex
from pysdocx.page import parse_page


def cmd_dump(args: argparse.Namespace) -> None:
    print(dump_container(args.file))


def _fmt_color(color: tuple[int, int, int] | None) -> str:
    return color_hex(color) or "(default)"


def _fmt_bbox(bbox: tuple[float, float, float, float]) -> str:
    return f"({bbox[0]:.1f},{bbox[1]:.1f})-({bbox[2]:.1f},{bbox[3]:.1f})"


def _fmt_optional_bbox(bbox: tuple[float, float, float, float] | None) -> str:
    return _fmt_bbox(bbox) if bbox is not None else "(none)"


def cmd_stroke_table(args: argparse.Namespace) -> None:
    page_names = list_pages(args.file)
    if args.page:
        page_names = [p for p in page_names if args.page in p]
        if not page_names:
            print(f"no .page file matches {args.page!r}", file=sys.stderr)
            sys.exit(1)

    any_mismatch = False
    for page_name in page_names:
        _, page_data = load_page(args.file, page_name)
        result = parse_page(page_data)
        short = result["uuid"][:8]
        mismatch = result["kept"] != result["stroke_count"]
        any_mismatch |= mismatch
        flag = "  MISMATCH" if mismatch else ""
        print(
            f"{short}  stroke_count={result['stroke_count']:>4}  "
            f"attempted={result['attempted']:>4}  kept={result['kept']:>4}{flag}"
        )

        if args.detail:
            print(
                f"  {'idx':>4} {'extra':>5} {'layout':>8} {'n_pts':>6} {'width':>7} "
                f"{'tool':>4} {'color':>8} {'bbox':<32} {'outcome'}"
            )
            for a in result["attempts"]:
                tool = a["tool_id"] if a["tool_id"] is not None else "?"
                print(
                    f"  {a['idx']:>4} {a['extra_len']:>5} {a['layout']:>8} "
                    f"{a['n_points_decoded']:>6} {a['pen_width']:>7.2f} "
                    f"{str(tool):>4} {_fmt_color(a['color']):>8} "
                    f"{_fmt_bbox(a['bbox']):<32} {a['outcome']}"
                )

    if any_mismatch:
        sys.exit(1)


def _print_object(obj: dict, depth: int, detail: bool, media_by_object: dict[int, list[dict]] | None = None) -> None:
    header = obj["header"] or {}
    indent = "  " * depth
    uuid = header.get("uuid", "")
    uuid_short = uuid[:8] if uuid else "-"
    print(
        f"{indent}{obj['idx']:>4} raw={obj['raw_type']:<3} type={obj['type']:<14} "
        f"size={obj['size']:>5} child={obj['child_count']:<3} off=0x{obj['off']:x} "
        f"bbox={_fmt_optional_bbox(obj['bbox'])} uuid={uuid_short}"
    )
    if detail and header:
        print(
            f"{indent}     header total={header['total_size']} var={header['var_data_offset']} "
            f"fmt={header['format_version']} flags=0x{header['flags']:x} "
            f"field=0x{header['field_flags']:x} mtime={header['modified_time']}"
        )
    if detail and media_by_object:
        for media in media_by_object.get(obj["off"], []):
            print(
                f"{indent}     media index={media['media_index']} "
                f"index_off=0x{media['media_index_off']:x} size={media['media_index_size']} "
                f"marker_off=0x{media['off']:x}"
            )
    for child in obj["children"]:
        _print_object(child, depth + 1, detail, media_by_object)


def _iter_cli_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        yield from _iter_cli_objects(obj["children"])


def _print_object_summary(page_results: list[dict]) -> None:
    counts = Counter()
    header_counts = Counter()
    total_objects = 0
    total_strokes = 0
    total_kept = 0
    for result in page_results:
        total_objects += result["object_count"]
        total_strokes += result["stroke_count"]
        total_kept += result["kept"]
        for layer in result["layers"]:
            for obj in _iter_cli_objects(layer["objects"]):
                counts[(obj["raw_type"], obj["type"])] += 1
                header = obj["header"]
                if header:
                    header_counts[(obj["raw_type"], obj["type"], header["total_size"], header["field_flags"])] += 1

    print(f"summary pages={len(page_results)} objects={total_objects} strokes={total_strokes} kept={total_kept}")
    for (raw_type, obj_type), count in sorted(counts.items()):
        print(f"  raw={raw_type:<3} type={obj_type:<14} count={count}")
        for (hraw, htype, total_size, field_flags), header_count in sorted(header_counts.items()):
            if (raw_type, obj_type) == (hraw, htype):
                print(f"      header total={total_size:<4} field=0x{field_flags:x} count={header_count}")


def cmd_objects(args: argparse.Namespace) -> None:
    page_names = list_pages(args.file)
    if args.page:
        page_names = [p for p in page_names if args.page in p]
        if not page_names:
            print(f"no .page file matches {args.page!r}", file=sys.stderr)
            sys.exit(1)

    page_results = []
    for page_name in page_names:
        _, page_data = load_page(args.file, page_name)
        page_results.append(parse_page(page_data))

    if args.summary:
        _print_object_summary(page_results)
        return

    for page_idx, result in enumerate(page_results, 1):
        print(
            f"{page_idx:>2}. {result['uuid'][:8]}  layers={len(result['layers'])}  "
            f"objects={result['object_count']}  strokes={result['stroke_count']}  kept={result['kept']}"
        )
        for layer in result["layers"]:
            media_by_object = defaultdict(list)
            for placement in result["images"] + result["drawings"]:
                media_by_object[placement["object_off"]].append(placement)
            current = " current" if layer["current"] else ""
            print(
                f"  layer {layer['idx']}{current} uuid={layer['uuid'][:8] or '-'} "
                f"objects={layer['object_count']} flags=0x{layer['content_flags']:02x}"
            )
            for obj in layer["objects"]:
                _print_object(obj, 2, args.detail, media_by_object)


def cmd_render(args: argparse.Namespace) -> None:
    # Imported lazily so `dump`/`stroke-table` don't pull in matplotlib/Pillow.
    from pysdocx.render import render_document

    out_dir = args.outdir or Path("outputs_render") / args.file.stem
    render_document(
        args.file,
        out=out_dir,
        fmt=args.format,
        bg=args.bg,
        page=args.page,
        table_page=args.table_page,
        show=False,
    )
    stem = args.file.stem
    pages = [args.page] if args.page else "all"
    print(f"wrote {stem}-page-NN.{args.format} to {out_dir} (pages: {pages})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m pysdocx")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="list a .sdocx archive's contents")
    p_dump.add_argument("file", type=Path)
    p_dump.set_defaults(func=cmd_dump)

    p_table = sub.add_parser("stroke-table", help="per-page stroke parse diagnostics")
    p_table.add_argument("file", type=Path)
    p_table.add_argument("--page", help="filter to .page files whose name contains this substring")
    p_table.add_argument("--detail", action="store_true", help="print one row per attempted stroke")
    p_table.set_defaults(func=cmd_stroke_table)

    p_objects = sub.add_parser("objects", help="print the parsed page layer/object tree")
    p_objects.add_argument("file", type=Path)
    p_objects.add_argument("--page", help="filter to .page files whose name contains this substring")
    p_objects.add_argument("--detail", action="store_true", help="print object header details")
    p_objects.add_argument("--summary", action="store_true", help="print aggregate object type counts")
    p_objects.set_defaults(func=cmd_objects)

    p_render = sub.add_parser("render", help="render each page to an image (one file per page)")
    p_render.add_argument("file", type=Path)
    p_render.add_argument(
        "outdir", type=Path, nargs="?", help="output directory (default: outputs_render/<file stem>/)"
    )
    p_render.add_argument("--format", default="png", choices=("png", "svg"), help="output image format")
    p_render.add_argument("--page", type=int, help="render only this 1-based page index")
    p_render.add_argument("--table-page", type=int, help="force note-level table rendering onto this page")
    p_render.add_argument("--bg", choices=("dark", "white"), help="page background (default: the file's stored color)")
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
