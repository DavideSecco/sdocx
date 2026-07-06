"""Regression gate: the Kaitai `.ksy` specs must agree with `pysdocx` on the corpus.

Each spec in `spec/ksy/` is compiled to a Python parser (vendored in
`spec/generated/`, regenerate with `spec/tools/regenerate.sh`). This test parses
every corpus sample with both the generated Kaitai parser and the reference
`pysdocx` parser and asserts the decoded fields match. If a `.ksy` and `pysdocx`
diverge — or `pysdocx` drifts — this fails.

Needs only the pure-Python `kaitaistruct` runtime (no compiler); skips cleanly if
it or the generated parsers are absent.
"""
import struct
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "spec" / "generated"
SAMPLES = ROOT / "samples"
sys.path.insert(0, str(GENERATED))

try:
    import kaitaistruct  # noqa: F401
    from sdocx_end_tag import SdocxEndTag
    from sdocx_media_info import SdocxMediaInfo
    from sdocx_note import SdocxNote
    from sdocx_object_header import SdocxObjectHeader
    from sdocx_page import SdocxPage
    from sdocx_page_id_info import SdocxPageIdInfo
    _KAITAI_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - environment dependent
    _KAITAI_AVAILABLE = False
    _IMPORT_ERROR = exc

from pysdocx.container import parse_end_tag, parse_media_info, parse_page_id_info  # noqa: E402
from pysdocx.note import parse_note_metadata  # noqa: E402
from pysdocx.page import (  # noqa: E402
    _iter_objects,
    _parse_object_header,
    parse_page,
    parse_page_tree,
)


def _samples():
    return sorted(SAMPLES.glob("*.sdocx"))


def _member(sample: Path, name: str) -> bytes | None:
    with zipfile.ZipFile(sample) as z:
        if name not in z.namelist():
            return None
        return z.read(name)


@unittest.skipUnless(_KAITAI_AVAILABLE, "kaitaistruct runtime / generated parsers not available")
class KaitaiSpecMatchesPysdocx(unittest.TestCase):
    """Every decoded field in each spec matches the reference parser, corpus-wide."""

    def setUp(self) -> None:
        if not _samples():
            self.skipTest("no corpus samples present")

    def test_end_tag(self) -> None:
        checked = 0
        for sample in _samples():
            data = _member(sample, "end_tag.bin")
            if data is None:
                continue
            ref, k = parse_end_tag(data), SdocxEndTag.from_bytes(data)
            for f in ("payload_size", "format_version", "format_version_dup",
                      "modified_time", "page_width", "created_time_header",
                      "created_time_a", "created_time_b", "extra_time_candidate"):
                self.assertEqual(ref[f], getattr(k, f), f"{sample.name}: {f}")
            self.assertEqual(k.signature, "Document for S-Pen SDK", sample.name)
            checked += 1
        self.assertGreater(checked, 0)

    def test_page_id_info(self) -> None:
        checked = 0
        for sample in _samples():
            data = _member(sample, "pageIdInfo.dat")
            if data is None:
                continue
            ref, k = parse_page_id_info(data), SdocxPageIdInfo.from_bytes(data)
            self.assertEqual(k.head_hash.hex(), ref["head_hash"], sample.name)
            self.assertEqual(k.page_count, ref["page_count"], sample.name)
            for i, (kp, rp) in enumerate(zip(k.pages, ref["records"])):
                self.assertEqual(kp.uuid, rp["uuid"], f"{sample.name}: pages[{i}].uuid")
                self.assertEqual(kp.page_hash.hex(), rp["page_hash"], f"{sample.name}: pages[{i}].page_hash")
            checked += 1
        self.assertGreater(checked, 0)

    def test_media_info(self) -> None:
        checked = 0
        for sample in _samples():
            data = _member(sample, "media/mediaInfo.dat")
            if data is None:
                continue
            ref, k = parse_media_info(data), SdocxMediaInfo.from_bytes(data)
            self.assertEqual(k.magic, ref["magic"], sample.name)
            self.assertEqual(k.record_count, ref["count"], sample.name)
            self.assertEqual(k.eof, "EOFX", sample.name)
            for i, (kr, rr) in enumerate(zip(k.records, ref["records"])):
                self.assertEqual(kr.body.media_index, rr["media_index"], f"{sample.name}: rec[{i}].media_index")
                self.assertEqual(kr.body.name, rr["name"], f"{sample.name}: rec[{i}].name")
                self.assertEqual(kr.body.sha256, rr["sha256"], f"{sample.name}: rec[{i}].sha256")
            checked += 1
        self.assertGreater(checked, 0)

    def test_note_header(self) -> None:
        checked = 0
        for sample in _samples():
            data = _member(sample, "note.note")
            if data is None:
                continue
            ref, k = parse_note_metadata(data), SdocxNote.from_bytes(data)
            for f in ("offset_to_data", "flags", "meta_flags", "format_version",
                      "file_revision", "created_time", "modified_time", "width",
                      "height", "page_h_padding", "page_v_padding",
                      "min_format_version", "title_size"):
                self.assertEqual(ref[f], getattr(k, f), f"{sample.name}: {f}")
            self.assertEqual(ref["note_id"], k.note_id.value, f"{sample.name}: note_id")
            checked += 1
        self.assertGreater(checked, 0)

    def test_object_header(self) -> None:
        base_fields = ("total_size", "data_type", "var_data_offset", "flags",
                       "field_flags", "format_version", "uuid", "modified_time",
                       "timestamp", "resizable")
        checked = 0
        for sample in _samples():
            with zipfile.ZipFile(sample) as z:
                for name in sorted(n for n in z.namelist() if n.endswith(".page")):
                    data = z.read(name)
                    try:
                        base = parse_page(data)["base"]
                    except ValueError:
                        continue
                    tree = parse_page_tree(data, 0, 0, base)
                    for layer in tree["layers"]:
                        for obj in _iter_objects(layer["objects"]):
                            blob = data[obj["blob_off"]:obj["end"]]
                            ref = _parse_object_header(blob)
                            if ref is None:
                                continue
                            k = SdocxObjectHeader.from_bytes(blob)
                            where = f"{sample.name}/{name[:12]} obj@{obj['blob_off']}"
                            for f in base_fields:
                                self.assertEqual(ref[f], getattr(k, f), f"{where}: {f}")
                            self.assertEqual(
                                struct.pack("<4d", *k.bbox),
                                struct.pack("<4d", *ref["bbox"]), f"{where}: bbox")
                            if ref["field_flags"] & 0x20:
                                ek = ref["extra_key_block"]
                                self.assertIsNotNone(k.extra_key, f"{where}: extra_key")
                                self.assertEqual(k.extra_key.key.rstrip("\x00"), ek["key"], f"{where}: extra_key.key")
                                self.assertEqual(k.extra_key.trailing, ek["trailing"], f"{where}: extra_key.trailing")
                            if ref["field_flags"] & 0x40000:
                                ex = ref["ext_block"]
                                self.assertIsNotNone(k.hdr_ext, f"{where}: hdr_ext")
                                self.assertEqual(
                                    (k.hdr_ext.counter, k.hdr_ext.seq, k.hdr_ext.page_width, k.hdr_ext.page_height),
                                    (ex["counter"], ex["seq"], ex["page_width"], ex["page_height"]), f"{where}: hdr_ext")
                            checked += 1
        self.assertGreater(checked, 0)

    def test_page_header(self) -> None:
        checked = 0
        for sample in _samples():
            with zipfile.ZipFile(sample) as z:
                page_names = sorted(n for n in z.namelist() if n.endswith(".page"))
                for name in page_names:
                    data = z.read(name)
                    try:
                        ref = parse_page(data)
                    except ValueError:
                        continue
                    k = SdocxPage.from_bytes(data)
                    self.assertEqual(k.base, ref["base"], f"{sample.name}/{name}")
                    self.assertEqual(k.page_width, ref["width"], f"{sample.name}/{name}")
                    self.assertEqual(k.page_height, ref["height"], f"{sample.name}/{name}")
                    self.assertEqual(k.uuid, ref["uuid"], f"{sample.name}/{name}")
                    # Bytewise: empty pages leave content_bbox uninitialised (NaN).
                    self.assertEqual(
                        struct.pack("<4d", *k.content_bbox),
                        struct.pack("<4d", *ref["content_bbox"]),
                        f"{sample.name}/{name}: content_bbox",
                    )
                    checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
