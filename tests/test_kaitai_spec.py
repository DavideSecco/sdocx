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
    from sdocx_payload_geometry import SdocxPayloadGeometry
    from sdocx_page_id_info import SdocxPageIdInfo
    _KAITAI_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - environment dependent
    _KAITAI_AVAILABLE = False
    _IMPORT_ERROR = exc

from pysdocx.container import parse_end_tag, parse_media_info, parse_page_id_info  # noqa: E402
from pysdocx.note import parse_note_metadata  # noqa: E402
from pysdocx.page import (  # noqa: E402
    _decode_payload_geometry,
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


def _flatten_kaitai_objects(objects, pos: int):
    out = []
    for obj in objects:
        blob_off = pos + 7
        end = blob_off + obj.blob_size
        out.append({
            "off": pos,
            "blob_off": blob_off,
            "end": end,
            "raw_type": obj.raw_type,
            "child_count": obj.child_count,
            "size": obj.blob_size,
        })
        child_rows, pos = _flatten_kaitai_objects(obj.children, end)
        out.extend(child_rows)
    return out, pos


def _kaitai_layer_static_and_optional_len(layer) -> int:
    n = 16
    if layer.content_flags & 0x01:
        n += 1
    if layer.content_flags & 0x02:
        n += 4
    if layer.content_flags & 0x04:
        n += 2 + layer.content_04_text.char_len * 2
    if layer.content_flags & 0x08:
        n += 2 + layer.layer_uuid.char_len * 2
    if layer.content_flags & 0x10:
        n += 8
    if layer.content_flags & 0x20:
        n += 4
    return n


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
                      "document_height", "created_time_a", "created_time_b",
                      "extra_time_candidate"):
                self.assertEqual(ref[f], getattr(k, f), f"{sample.name}: {f}")
            self.assertEqual(k.signature, "Document for S-Pen SDK", sample.name)
            note = _member(sample, "note.note")
            if note is not None:
                note_ref = parse_note_metadata(note)
                self.assertEqual(k.document_height, float(note_ref["height"]), f"{sample.name}: document_height")
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
            # Cross-file linkage: head_hash is a copy of note.note's trailing 32 bytes.
            note = _member(sample, "note.note")
            if note is not None:
                self.assertEqual(ref["head_hash"], note[-32:].hex(), f"{sample.name}: head_hash!=note[-32:]")
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
                self.assertEqual(kr.body.tail.tag, rr["tail_tag"], f"{sample.name}: rec[{i}].tail.tag")
                self.assertEqual(
                    kr.body.tail.time_candidate,
                    rr["time_candidate"],
                    f"{sample.name}: rec[{i}].tail.time_candidate",
                )
                self.assertEqual(kr.body.tail.marker, rr["tail_marker"], f"{sample.name}: rec[{i}].tail.marker")
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
            tail_sentinel = next(r for r in ref["tail_records"] if r["kind"] == "tail_sentinel")
            self.assertEqual(k.tail_sentinel.hex(), tail_sentinel["signature"], f"{sample.name}: tail_sentinel")
            self.assertEqual(k.trailing_hash.hex(), data[-32:].hex(), f"{sample.name}: trailing_hash")
            tail_hash = next(r for r in ref["tail_records"] if r["kind"] == "tail_hash_block")
            candidates = []
            if tail_hash["off"] == len(data) - 40:
                candidates.append(k.tail_hash_block_eof)
            if tail_hash["off"] == len(data) - 44:
                candidates.append(k.tail_hash_block_before_post_u32)
            self.assertEqual(len(candidates), 1, f"{sample.name}: modeled tail_hash_block boundary")
            block = candidates[0]
            self.assertEqual(block.prefix_u32, tail_hash["prefix_u32"], f"{sample.name}: tail_hash.prefix")
            self.assertEqual(block.hash32.hex(), tail_hash["hash32"], f"{sample.name}: tail_hash.hash32")
            for record in ref["tail_records"]:
                if record["kind"] == "tail_post_hash_u32":
                    self.assertEqual(
                        record["value"],
                        struct.unpack_from("<I", data, len(data) - 4)[0],
                        f"{sample.name}: tail_post_hash_u32",
                    )
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

    def test_payload_geometry(self) -> None:
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
                            header = _parse_object_header(blob)
                            ref = _decode_payload_geometry(blob, header)
                            if ref is None:
                                continue
                            k = SdocxPayloadGeometry.from_bytes(blob[header["total_size"]:])
                            where = f"{sample.name}/{name[:12]} obj@{obj['blob_off']}"
                            self.assertEqual((k.l0, k.tag, k.l1), (ref["l0"], ref["tag"], ref["l1"]), f"{where}: lengths")
                            self.assertEqual(k.point_count, ref["point_count"], f"{where}: point_count")
                            self.assertEqual([(p.x, p.y) for p in k.points], ref["points"], f"{where}: points")
                            checked += 1
        self.assertGreater(checked, 0)

    def test_page_header(self) -> None:
        checked = 0
        for sample in _samples():
            with zipfile.ZipFile(sample) as z:
                manifest = parse_page_id_info(z.read("pageIdInfo.dat")) if "pageIdInfo.dat" in z.namelist() else None
                manifest_hash = {r["uuid"]: r["page_hash"] for r in (manifest or {}).get("records", ())}
                page_names = sorted(n for n in z.namelist() if n.endswith(".page"))
                for name in page_names:
                    data = z.read(name)
                    try:
                        ref = parse_page(data)
                    except ValueError:
                        continue
                    k = SdocxPage.from_bytes(data)
                    where = f"{sample.name}/{name}"
                    self.assertEqual(k.base, ref["base"], where)
                    self.assertEqual(k.page_width, ref["width"], where)
                    self.assertEqual(k.page_height, ref["height"], where)
                    self.assertEqual(k.uuid, ref["uuid"], where)
                    # Bytewise: empty pages leave content_bbox uninitialised (NaN).
                    self.assertEqual(
                        struct.pack("<4d", *k.content_bbox),
                        struct.pack("<4d", *ref["content_bbox"]),
                        f"{where}: content_bbox",
                    )
                    self.assertEqual(k.footer_signature, "Page for SAMSUNG S-Pen SDK", where)
                    self.assertEqual(k.page_hash.hex(), ref["footer"]["page_hash"], f"{where}: page_hash")
                    # Cross-file linkage: page footer hash IS the pageIdInfo manifest hash.
                    if ref["uuid"] in manifest_hash:
                        self.assertEqual(k.page_hash.hex(), manifest_hash[ref["uuid"]], f"{where}: page_hash!=manifest")
                    checked += 1
        self.assertGreater(checked, 0)

    def test_page_tree(self) -> None:
        checked_pages = checked_objects = 0
        for sample in _samples():
            with zipfile.ZipFile(sample) as z:
                for name in sorted(n for n in z.namelist() if n.endswith(".page")):
                    data = z.read(name)
                    try:
                        ref_page = parse_page(data)
                    except ValueError:
                        continue
                    ref = parse_page_tree(data, ref_page["width"], ref_page["height"], ref_page["base"])
                    k = SdocxPage.from_bytes(data)
                    kt = k.tree
                    where = f"{sample.name}/{name}"
                    self.assertEqual(kt.layer_count, len(ref["layers"]), f"{where}: layer_count")
                    self.assertEqual(kt.current_layer_index, ref["current_layer_index"], f"{where}: current_layer")

                    pos = k.base + 4
                    for i, (kl, rl) in enumerate(zip(kt.layers, ref["layers"])):
                        prefix_off = pos
                        layer_off = prefix_off + 4
                        self.assertEqual(layer_off, rl["off"], f"{where}: layer[{i}].off")
                        self.assertEqual(kl.layer_prefix, rl["prefix"], f"{where}: layer[{i}].prefix")
                        self.assertEqual(kl.next_offset, rl["next_offset"], f"{where}: layer[{i}].next_offset")
                        self.assertEqual((kl.flag1, kl.flag2, kl.flag3), rl["flags"], f"{where}: layer[{i}].flags")
                        self.assertEqual(kl.content_flags, rl["content_flags"], f"{where}: layer[{i}].content_flags")
                        self.assertEqual(kl.layer_flags, rl["layer_flags"], f"{where}: layer[{i}].layer_flags")
                        got_uuid = kl.layer_uuid.value if kl.content_flags & 0x08 else ""
                        self.assertEqual(got_uuid, rl["uuid"], f"{where}: layer[{i}].uuid")
                        got_modified = kl.modified_time if kl.content_flags & 0x10 else None
                        self.assertEqual(got_modified, rl["modified_time"], f"{where}: layer[{i}].modified_time")
                        self.assertEqual(kl.object_count, rl["object_count"], f"{where}: layer[{i}].object_count")

                        objects_pos = prefix_off + _kaitai_layer_static_and_optional_len(kl) + 4
                        k_objects, end_pos = _flatten_kaitai_objects(kl.objects, objects_pos)
                        r_objects = list(_iter_objects(rl["objects"]))
                        self.assertEqual(len(k_objects), len(r_objects), f"{where}: layer[{i}].recursive_object_count")
                        for j, (ko, ro) in enumerate(zip(k_objects, r_objects)):
                            for field in ("off", "blob_off", "end", "raw_type", "child_count", "size"):
                                self.assertEqual(ko[field], ro[field], f"{where}: layer[{i}].object[{j}].{field}")
                        self.assertEqual(kl.layer_hash.hex(), rl["hash"], f"{where}: layer[{i}].hash")
                        checked_objects += len(k_objects)
                        pos = end_pos + 32
                    checked_pages += 1
        self.assertGreater(checked_pages, 0)
        self.assertGreater(checked_objects, 0)


if __name__ == "__main__":
    unittest.main()
