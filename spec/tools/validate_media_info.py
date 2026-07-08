"""Cross-check the Kaitai mediaInfo spec against pysdocx on the whole corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_media_info.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_media_info import SdocxMediaInfo  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.container import parse_media_info  # noqa: E402


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
            if "media/mediaInfo.dat" not in z.namelist():
                print(f"SKIP  {sample.name}: no mediaInfo.dat")
                continue
            data = z.read("media/mediaInfo.dat")
        ref = parse_media_info(data)
        k = SdocxMediaInfo.from_bytes(data)
        diffs = []
        if k.format_version != ref["format_version"]:
            diffs.append("format_version")
        if k.record_count != ref["count"]:
            diffs.append("count")
        if k.eof != "EOFX":
            diffs.append("eof")
        for i, (kr, rr) in enumerate(zip(k.records, ref["records"])):
            b = kr.body
            if b.media_index != rr["media_index"]:
                diffs.append(f"records[{i}].media_index")
            if b.name != rr["name"]:
                diffs.append(f"records[{i}].name")
            if b.sha256 != rr["sha256"]:
                diffs.append(f"records[{i}].sha256")
            if b.tail.ref_count != rr["ref_count"]:
                diffs.append(f"records[{i}].tail.ref_count")
            if b.tail.modified_time != rr["modified_time"]:
                diffs.append(f"records[{i}].tail.modified_time")
            if b.tail.is_attached != int(rr["is_attached"]):
                diffs.append(f"records[{i}].tail.is_attached")
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: {diffs}")
        else:
            ok += 1
            print(f"OK    {sample.name} ({ref['count']} records)")
    print(f"\n{ok} matched, {failures} mismatched, out of {ok + failures} parsed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
