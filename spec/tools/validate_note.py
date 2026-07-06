"""Cross-check the Kaitai note.note header spec against pysdocx on the corpus.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_note.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_note import SdocxNote  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.note import parse_note_metadata  # noqa: E402

FIELDS = [
    "offset_to_data",
    "flags",
    "meta_flags",
    "format_version",
    "file_revision",
    "created_time",
    "modified_time",
    "width",
    "height",
    "page_h_padding",
    "page_v_padding",
    "min_format_version",
    "title_size",
]


def main() -> int:
    ok = failures = 0
    for sample in sorted((ROOT / "samples").glob("*.sdocx")):
        with zipfile.ZipFile(sample) as z:
            if "note.note" not in z.namelist():
                print(f"SKIP  {sample.name}: no note.note")
                continue
            data = z.read("note.note")
        ref = parse_note_metadata(data)
        k = SdocxNote.from_bytes(data)
        got = {f: getattr(k, f) for f in FIELDS}
        got["note_id"] = k.note_id.value
        diffs = [f for f in FIELDS if ref.get(f) != got.get(f)]
        if ref.get("note_id") != got["note_id"]:
            diffs.append("note_id")
        if diffs:
            failures += 1
            print(f"FAIL  {sample.name}: {diffs}")
            for f in diffs:
                print(f"        {f}: pysdocx={ref.get(f)!r} kaitai={got.get(f)!r}")
        else:
            ok += 1
            print(f"OK    {sample.name} (fmt={ref['format_version']} meta=0x{ref['meta_flags']:x})")
    print(f"\n{ok} matched, {failures} mismatched, out of {ok + failures} parsed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
