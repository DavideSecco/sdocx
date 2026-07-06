"""Cross-check the Kaitai end_tag spec against pysdocx on the whole corpus.

Run with the session venv and the generated parser + kaitai runtime on sys.path:
    KSC_GEN=<dir with sdocx_end_tag.py> .venv/bin/python spec/tools/validate_end_tag.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))

from sdocx_end_tag import SdocxEndTag  # noqa: E402  (generated Kaitai parser)

sys.path.insert(0, str(ROOT))
from pysdocx.container import parse_end_tag  # noqa: E402

FIELDS = [
    "payload_size",
    "format_version",
    "format_version_dup",
    "modified_time",
    "page_width",
    "created_time_header",
    "created_time_a",
    "created_time_b",
    "extra_time_candidate",
]


def kaitai_fields(data: bytes) -> dict:
    k = SdocxEndTag.from_bytes(data)
    return {
        "payload_size": k.payload_size,
        "format_version": k.format_version,
        "format_version_dup": k.format_version_dup,
        "modified_time": k.modified_time,
        "page_width": k.page_width,
        "created_time_header": k.created_time_header,
        "created_time_a": k.created_time_a,
        "created_time_b": k.created_time_b,
        "extra_time_candidate": k.extra_time_candidate,
        "signature": k.signature,
    }


def main() -> int:
    samples = sorted((ROOT / "samples").glob("*.sdocx"))
    ok = 0
    failures = 0
    for sample in samples:
        with zipfile.ZipFile(sample) as z:
            if "end_tag.bin" not in z.namelist():
                print(f"SKIP  {sample.name}: no end_tag.bin")
                continue
            data = z.read("end_tag.bin")
        ref = parse_end_tag(data)
        got = kaitai_fields(data)
        diffs = [f for f in FIELDS if ref.get(f) != got.get(f)]
        if got["signature"] != "Document for S-Pen SDK":
            diffs.append("signature")
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: mismatched {diffs}")
            for f in diffs:
                print(f"        {f}: pysdocx={ref.get(f)!r} kaitai={got.get(f)!r}")
        else:
            ok += 1
            print(f"OK    {sample.name}")
    print(f"\n{ok} matched, {failures} mismatched, out of {ok + failures} parsed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
