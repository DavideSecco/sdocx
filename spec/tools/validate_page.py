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
from pysdocx.page import parse_page  # noqa: E402


def main() -> int:
    ok = failures = pages = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
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
                # Compare bytewise: empty pages leave content_bbox uninitialised
                # (NaN + denormals), and NaN != NaN would give a false mismatch.
                if struct.pack("<4d", *k.content_bbox) != struct.pack("<4d", *ref["content_bbox"]):
                    diffs.append("content_bbox")
                if diffs:
                    failures += 1
                    print(f"FAIL  {sample.name}/{name[:12]}: {diffs}")
                else:
                    ok += 1
    print(f"\n{ok} matched, {failures} mismatched, out of {pages} pages")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
