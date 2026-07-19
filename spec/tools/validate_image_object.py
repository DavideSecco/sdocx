"""Cross-check the Kaitai image-object crop spec against pysdocx across the corpus.

For every imported-image placement in every corpus note — page-object images
(`scan_images_from_objects`) and note.note inline images — feed the record
starting at its media-reference marker to the generated `sdocx_image_object`
Kaitai parser and assert its crop decode matches pysdocx: the media index, the
crop-present flag, and (when cropped) the normalized source crop derived from
the full-image rect + the placement bbox.

    KSC_GEN=<gen dir> .venv/bin/python spec/tools/validate_image_object.py
"""
import os
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("KSC_GEN", str(ROOT / "spec" / "generated")))
from sdocx_image_object import SdocxImageObject  # noqa: E402

sys.path.insert(0, str(ROOT))
from pysdocx.container import list_pages, load_note  # noqa: E402
from pysdocx.page import (  # noqa: E402
    IMAGE_MARKER,
    IMAGE_MEDIA_REF_MARKER,
    IMAGE_BBOX_FWD,
    _image_crop,
    _image_media_index,
    parse_page,
)
from pysdocx.note_doc import (  # noqa: E402
    NoteDocParseError,
    note_doc_common_frames,
    parse_note_doc,
)


def _ksy_view(record: bytes, marker: int) -> dict | None:
    """Kaitai's read of the crop flex, fed the record from the media-ref marker."""
    ref = record.find(IMAGE_MEDIA_REF_MARKER, marker, min(len(record), marker + 180))
    if ref < 0:
        return None
    k = SdocxImageObject.from_bytes(record[ref:])
    rect = None
    if k.is_cropped:
        r = k.crop_full_rect
        rect = (r.x0, r.y0, r.x1, r.y1)
    return {"media_index": k.media_index, "is_cropped": k.is_cropped, "rect": rect}


def _diffs(record: bytes, marker: int, bbox: tuple) -> list[str]:
    got = _ksy_view(record, marker)
    if got is None:
        return ["no media reference"]
    diffs = []
    ref_media, _, _ = _image_media_index(record, marker, len(record))
    if got["media_index"] != ref_media:
        diffs.append(f"media_index {got['media_index']} != {ref_media}")
    ref_crop = _image_crop(record, marker, bbox, len(record))
    if got["is_cropped"] != (ref_crop is not None):
        diffs.append(f"is_cropped {got['is_cropped']} != {ref_crop is not None}")
    elif ref_crop is not None:
        x0, y0, x1, y1 = got["rect"]
        norm = {
            "x": (bbox[0] - x0) / (x1 - x0),
            "y": (bbox[1] - y0) / (y1 - y0),
            "w": (bbox[2] - bbox[0]) / (x1 - x0),
            "h": (bbox[3] - bbox[1]) / (y1 - y0),
        }
        if any(abs(norm[k] - ref_crop[k]) > 1e-9 for k in ("x", "y", "w", "h")):
            diffs.append(f"crop {norm} != {ref_crop}")
    return diffs


def _image_records(sample: Path):
    """Yield (label, record_bytes, marker_off, bbox) for every image in a sample."""
    for page_name in list_pages(sample):
        with zipfile.ZipFile(sample) as z:
            data = z.read(page_name)
        for im in parse_page(data)["images"]:
            yield f"{page_name[:8]}", data, im["off"], im["bbox"]
    note = load_note(sample)
    if note is None:
        return
    try:
        doc = parse_note_doc(note)
        body = note_doc_common_frames(note, doc)["body"]
    except (NoteDocParseError, UnicodeDecodeError, struct.error, KeyError):
        return
    if not body:
        return
    body_off = doc["body_off"]
    for obj in body.get("inline", {}).get("objects", []):
        if obj.get("object_type") != 3:
            continue
        blob = note[body_off + obj["body_off"] : body_off + obj["body_off"] + obj["obj_size"]]
        marker = blob.find(IMAGE_MARKER)
        if marker < 0 or marker + IMAGE_BBOX_FWD + 32 > len(blob):
            continue
        bbox = struct.unpack_from("<4d", blob, marker + IMAGE_BBOX_FWD)
        yield "note.note-inline", blob, marker, bbox


def diffs_for_sample(sample: Path):
    """Yield (label, diffs) for every image record in `sample` (test gate entry)."""
    for label, record, marker, bbox in _image_records(sample):
        yield label, _diffs(record, marker, bbox)


def main() -> int:
    ok = failures = 0
    for sample in sorted(list((ROOT / "samples").glob("*.sdocx")) + list((ROOT / "samples").glob("*/note.sdocx"))):
        for label, record, marker, bbox in _image_records(sample):
            d = _diffs(record, marker, bbox)
            if d:
                failures += 1
                print(f"FAIL  {sample.name} {label}: {d}")
            else:
                ok += 1
    print(f"\n{ok} image records matched, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
