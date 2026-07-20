"""Cross-check the Kaitai .page header spec against pysdocx on every page of the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_page.py
"""
import os
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_page import SdocxPage  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.container import parse_page_id_info  # noqa: E402
from pysdocx.page import parse_page  # noqa: E402
from pysdocx.page_header import parse_page_header  # noqa: E402


def _rect(values) -> bytes:
    return struct.pack(f"<{len(values)}d", *(float(v) for v in values))


def _diff_header(k: "SdocxPage", header: dict) -> list[str]:
    """Field-by-field diff of the .ksy header against pysdocx.page_header's structural parse."""
    diffs = []
    fields = header["fields"]

    if k.uuid.value != header["uuid"]:
        diffs.append("uuid")
    if k.width != header["width"] or k.height != header["height"]:
        diffs.append("width/height")
    if k.orientation != header["orientation"]:
        diffs.append("orientation")
    if (k.offset_x, k.offset_y) != (header["offset_x"], header["offset_y"]):
        diffs.append("offset_x/offset_y")
    if k.format_version != header["format_version"]:
        diffs.append("format_version")
    if k.field_flags.value != header["field_flags"]:
        diffs.append("field_flags")

    kb_present = k.has_drawn_rect
    rb = fields.get("drawn_rect")
    if kb_present != (rb is not None):
        diffs.append("drawn_rect_presence")
    elif kb_present and _rect(k.drawn_rect) != _rect(rb):
        diffs.append("drawn_rect")

    if k.has_background_colour != ("background_colour" in fields):
        diffs.append("background_colour_presence")
    elif k.has_background_colour and k.background_colour.hex() != fields["background_colour"]:
        diffs.append("background_colour")

    if k.has_template_type != ("template_type" in fields):
        diffs.append("template_type_presence")
    elif k.has_template_type and k.template_type != fields["template_type"]:
        diffs.append("template_type")

    if k.has_pdf_data_items != ("pdf_data_items" in fields):
        diffs.append("pdf_data_items_presence")
    elif k.has_pdf_data_items:
        k_items = k.pdf_data_items.items
        r_items = fields["pdf_data_items"]
        if len(k_items) != len(r_items):
            diffs.append("pdf_data_items_count")
        else:
            for ki, ri in zip(k_items, r_items):
                if (ki.file_id, ki.page_index) != (ri["file_id"], ri["page_index"]):
                    diffs.append("pdf_data_items")
                    break

    if k.has_custom_objects != ("custom_objects" in fields):
        diffs.append("custom_objects_presence")
    elif k.has_custom_objects:
        k_objs = k.custom_objects.objects
        r_objs = fields["custom_objects"]
        if len(k_objs) != len(r_objs):
            diffs.append("custom_objects_count")
        else:
            for ko, ro in zip(k_objs, r_objs):
                if ko.body.uuid.value != ro["uuid"]:
                    diffs.append("custom_objects.uuid")
                    break
                if ko.body.custom_data.entries and "custom_data" not in (diffs or []):
                    k_custom = {e.key.value: e.value.value for e in ko.body.custom_data.entries}
                    if k_custom != ro["custom_data"]:
                        diffs.append("custom_objects.custom_data")
                        break

    return diffs


def main() -> int:
    ok = failures = pages = 0
    for sample in sorted(list((ROOT / "samples").glob("*.sdocx")) + list((ROOT / "samples").glob("*/note.sdocx"))):
        with zipfile.ZipFile(sample) as z:
            manifest = parse_page_id_info(z.read("pageIdInfo.dat")) if "pageIdInfo.dat" in z.namelist() else None
            manifest_hash = {r["uuid"]: r["page_hash"] for r in (manifest or {}).get("records", ())}
            page_names = [n for n in z.namelist() if n.endswith(".page")]
            for name in sorted(page_names):
                data = z.read(name)
                pages += 1
                try:
                    ref = parse_page(data)
                except ValueError:
                    print(f"SKIP  {sample.name}/{name}: pysdocx rejected header")
                    continue
                k = SdocxPage.from_bytes(data)
                diffs = []
                if k.base != ref["base"]:
                    diffs.append("base")
                if k.footer_signature != "Page for SAMSUNG S-Pen SDK":
                    diffs.append("footer_signature")
                if k.page_hash.hex() != ref["footer"]["page_hash"]:
                    diffs.append("page_hash")
                # Cross-file linkage: the page footer hash IS the pageIdInfo manifest hash.
                if ref["uuid"] in manifest_hash and k.page_hash.hex() != manifest_hash[ref["uuid"]]:
                    diffs.append("page_hash!=manifest")

                header = parse_page_header(data)
                diffs.extend(_diff_header(k, header))

                if diffs:
                    failures += 1
                    print(f"FAIL  {sample.name}/{name[:12]}: {diffs}")
                else:
                    ok += 1
    print(f"\n{ok} matched, {failures} mismatched, out of {pages} pages")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
