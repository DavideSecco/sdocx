"""CLI entry point: python -m pysdocx <command> ..."""

import argparse
import sys
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
