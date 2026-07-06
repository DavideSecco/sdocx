"""Cross-check the Kaitai pageIdInfo spec against pysdocx on the whole corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_page_id_info.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "gen")))
from sdocx_page_id_info import SdocxPageIdInfo  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.container import parse_page_id_info  # noqa: E402


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
            if "pageIdInfo.dat" not in z.namelist():
                print(f"SKIP  {sample.name}: no pageIdInfo.dat")
                continue
            data = z.read("pageIdInfo.dat")
        ref = parse_page_id_info(data)
        k = SdocxPageIdInfo.from_bytes(data)
        diffs = []
        if k.head_hash.hex() != ref["head_hash"]:
            diffs.append("head_hash")
        if k.page_count != ref["page_count"]:
            diffs.append("page_count")
        for i, (kp, rp) in enumerate(zip(k.pages, ref["records"])):
            if kp.uuid != rp["uuid"]:
                diffs.append(f"pages[{i}].uuid")
            if kp.page_hash.hex() != rp["page_hash"]:
                diffs.append(f"pages[{i}].page_hash")
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: {diffs}")
        else:
            ok += 1
            print(f"OK    {sample.name} ({ref['page_count']} pages)")
    print(f"\n{ok} matched, {failures} mismatched, out of {ok + failures} parsed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
