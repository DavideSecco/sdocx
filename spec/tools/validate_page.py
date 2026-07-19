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
                if k.page_width != ref["width"]:
                    diffs.append("width")
                if k.page_height != ref["height"]:
                    diffs.append("height")
                if k.uuid != ref["uuid"]:
                    diffs.append("uuid")
                kb = getattr(k, "content_bbox", None)
                rb = ref["content_bbox"]
                if (kb is None) != (rb is None):
                    diffs.append("content_bbox_presence")
                elif kb is not None and struct.pack("<4d", *kb) != struct.pack("<4d", *rb):
                    diffs.append("content_bbox")
                if k.footer_signature != "Page for SAMSUNG S-Pen SDK":
                    diffs.append("footer_signature")
                if k.page_hash.hex() != ref["footer"]["page_hash"]:
                    diffs.append("page_hash")
                # Cross-file linkage: the page footer hash IS the pageIdInfo manifest hash.
                if ref["uuid"] in manifest_hash and k.page_hash.hex() != manifest_hash[ref["uuid"]]:
                    diffs.append("page_hash!=manifest")
                if diffs:
                    failures += 1
                    print(f"FAIL  {sample.name}/{name[:12]}: {diffs}")
                else:
                    ok += 1
    print(f"\n{ok} matched, {failures} mismatched, out of {pages} pages")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
