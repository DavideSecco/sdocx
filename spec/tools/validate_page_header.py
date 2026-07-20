"""Validate `pysdocx.page_header.parse_page_header` against the whole corpus.

    .venv/bin/python spec/tools/validate_page_header.py

Checks, per `.page` member:
  * the fixed prefix ends exactly at `flex_offset` (raised as a parse error
    otherwise, not caught here — a hard failure);
  * the field-flags region consumes exactly `page_end_offset - flex_offset`
    bytes, landing on `pysdocx.page.parse_page`'s `base`;
  * cross-agreement with the pre-existing marker/heuristic scanners in
    `pysdocx/page.py` (`page_background_color`, `page_template`,
    `page_custom_template_uri`) wherever both mechanisms produce a result —
    see `pysdocx/page_header.py`'s module docstring for why these should
    agree byte-for-byte.

No `.ksy` exists for this surface yet (see docs/format/xref-sdocx2pdf.md);
this script is the gate for the pysdocx layer until one is ported.
"""
import os
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pysdocx.page import page_background_color, page_custom_template_uri, page_template  # noqa: E402
from pysdocx.page_header import PageHeaderParseError, parse_page_header  # noqa: E402


def _corpus_files():
    return sorted(
        list((ROOT / "samples").glob("*.sdocx")) + list((ROOT / "samples").glob("*/note.sdocx"))
    )


def main() -> int:
    pages = ok = 0
    parse_errors = []
    end_mismatches = []
    bg_disagree = []
    tmpl_disagree = []
    uri_disagree = []
    bits_seen = set()

    for sample in _corpus_files():
        with zipfile.ZipFile(sample) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".page")):
                data = z.read(name)
                pages += 1
                try:
                    header = parse_page_header(data)
                except PageHeaderParseError as exc:
                    parse_errors.append((sample.name, name, str(exc)))
                    continue

                bits_seen |= {b for b in range(32) if header["field_flags"] >> b & 1}

                if not header["reaches_page_end"]:
                    end_mismatches.append((
                        sample.name, name,
                        header["header_end_off"], header["page_end_offset"],
                    ))
                    continue

                fields = header["fields"]

                heur_bg = page_background_color(data)
                struct_bg_hex = fields.get("background_colour")
                if heur_bg is not None and struct_bg_hex is not None:
                    b = bytes.fromhex(struct_bg_hex)
                    struct_rgb = (b[2], b[1], b[0])  # BGRA -> RGB
                    if heur_bg != struct_rgb:
                        bg_disagree.append((sample.name, name, heur_bg, struct_rgb))

                heur_tmpl = page_template(data)
                struct_tmpl = fields.get("template_type")
                if heur_tmpl and heur_tmpl.get("kind") not in ("pdf", "image"):
                    heur_id = heur_tmpl.get("id")
                    if struct_tmpl is not None and heur_id is not None and heur_id != struct_tmpl:
                        tmpl_disagree.append((sample.name, name, heur_id, struct_tmpl))

                heur_uri = page_custom_template_uri(data)
                struct_uri = fields.get("template_uri")
                if heur_uri is not None and struct_uri is not None:
                    # Known heuristic quirk: an occasional stray leading UTF-16 code unit.
                    if heur_uri != struct_uri and heur_uri != "Z" + struct_uri:
                        uri_disagree.append((sample.name, name, heur_uri, struct_uri))

                ok += 1

    print(f"pages={pages} ok={ok} parse_errors={len(parse_errors)} end_mismatches={len(end_mismatches)}")
    print(f"field_flags bits ever seen: {sorted(bits_seen)}")
    print(f"background_colour disagreements: {len(bg_disagree)}")
    print(f"template_type disagreements: {len(tmpl_disagree)}")
    print(f"template_uri disagreements: {len(uri_disagree)}")

    for row in parse_errors[:10]:
        print("  PARSE ERROR", row)
    for row in end_mismatches[:10]:
        print("  END MISMATCH", row)
    for row in bg_disagree[:10]:
        print("  BG DISAGREE", row)
    for row in tmpl_disagree[:10]:
        print("  TEMPLATE DISAGREE", row)
    for row in uri_disagree[:10]:
        print("  URI DISAGREE", row)

    failed = parse_errors or end_mismatches or bg_disagree or tmpl_disagree or uri_disagree
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
