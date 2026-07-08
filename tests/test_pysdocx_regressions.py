import unittest
from pathlib import Path

from pysdocx.container import list_pages, load_page
from pysdocx.inventory import build_inventory
from pysdocx.page import parse_page
from pysdocx.render import debug_text_box_layout
from spec.tools.analyze_note_doc import collect as collect_note_doc
from spec.tools.analyze_sdocx2pdf_leads import collect as collect_sdocx2pdf_leads


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
ONLY_TEXT_SQUARED = SAMPLES / "OnlyTextTypeWritten_squared_260703_013624.sdocx"


def require_sample(path: Path) -> None:
    if not path.exists():
        raise unittest.SkipTest(f"sample fixture not available: {path}")


class InventoryRegressionTest(unittest.TestCase):
    def test_sdocx2pdf_lead_diagnostics(self) -> None:
        require_sample(SAMPLES)

        report = collect_sdocx2pdf_leads([SAMPLES])
        summary = report["summary"]

        self.assertEqual(summary["end_tag_files"], 14)
        self.assertEqual(summary["end_tag_page_models"], {0: 11, 1: 3})
        self.assertEqual(
            summary["end_tag_variant_gaps"],
            {
                "nonzero_property_flags": 0,
                "landscape": 0,
                "nonempty_sdk_strings": 0,
                "skipped_blocks": 0,
                "encryption_blocks": 0,
            },
        )
        self.assertEqual(summary["note_text_surfaces"], 22)
        self.assertEqual(summary["note_text_common_frame_hits"], 20)
        self.assertEqual(summary["text_boxes"], 8)
        self.assertEqual(summary["text_common_frame_hits"], 2)
        self.assertEqual(summary["media_objects"], 59)
        self.assertEqual(summary["media_known_ref_u32_hits"], 59)
        self.assertEqual(summary["media_by_kind"], {"image": 58, "painting": 1})
        self.assertEqual(summary["voice_clips"], 2)
        self.assertEqual(summary["voice_clips_linked_to_audio_media"], 2)
        self.assertEqual(summary["page_audio_type10_objects"], 0)

    def test_note_tail_inventory_counts(self) -> None:
        require_sample(SAMPLES)

        report = build_inventory([SAMPLES])
        tail = report["note_tail_profiles"]
        coverage = tail["coverage"]

        self.assertEqual(report["sample_count"], 14)
        self.assertEqual(tail["kinds"]["tail_sentinel"], 14)
        self.assertEqual(tail["kinds"]["tail_hash_block"], 14)
        self.assertEqual(tail["kinds"]["pen_preload_path"], 44)
        self.assertEqual(tail["kinds"]["pen_preload_prelude"], 27)
        self.assertEqual(tail["kinds"]["pen_preload_prelude_raw"], 16)
        self.assertEqual(tail["kinds"]["pen_style_tail"], 11)
        self.assertEqual(tail["kinds"]["voice_clip"], 2)
        self.assertEqual(coverage["known_bytes"], 6752)
        self.assertEqual(coverage["unknown_bytes"], 0)
        self.assertEqual(
            tail["preload_prelude_params"],
            {
                "10;": 2,
                "13;": 3,
                "14;": 3,
                "15;0;100;": 1,
                "18;0;100;": 4,
                "4;": 2,
                "5;": 3,
                "7;": 1,
                "8;": 8,
            },
        )
        self.assertEqual(tail["pen_style_tail_params"], {"5;": 1, "8;": 2})
        self.assertEqual(
            tail["voice_post_u64_pairs"],
            [
                {"post_u64_pairs": [1782811623648, 4294967298, 1782811624460528], "count": 1},
                {"post_u64_pairs": [1782923525248, 4294967298, 1782923525405332], "count": 1},
            ],
        )
        self.assertEqual(
            tail["voice_media_links"],
            {
                "voice_actual_duration_ms_candidate": 2,
                "voice_media_index_candidate": 2,
                "voice_media_time_candidate": 2,
            },
        )
        self.assertEqual(
            tail["page_id_info_relations"],
            {"page_id_head_exact": 11, "page_id_head_shifted_u32_2": 3},
        )
        media = report["media_info_profiles"]
        self.assertEqual(media["parsed_files"], 14)
        self.assertEqual(media["records"], 222)
        self.assertEqual(media["format_versions"], {"5202": 1, "5304": 1, "5400": 12})
        self.assertEqual(media["ref_counts"], {"1": 216, "20": 1, "3": 4, "5": 1})
        self.assertEqual(media["is_attached"], {"True": 222})
        self.assertEqual(media["magic"], {"0x1452": 1, "0x14b8": 1, "0x1518": 12})
        self.assertEqual(media["tail_tags"], {"1": 216, "20": 1, "3": 4, "5": 1})
        self.assertEqual(media["sha_mismatches"], 0)
        self.assertEqual(media["missing_media"], 0)
        self.assertEqual(media["unlisted_media"], 0)
        self.assertEqual(media["bad_eof"], 0)
        end_tag = report["end_tag_profiles"]
        self.assertEqual(end_tag["parsed_files"], 14)
        self.assertEqual(end_tag["payload_sizes"], {"142": 1, "146": 13})
        self.assertEqual(end_tag["format_versions"], {"4000": 10, "5400": 4})
        self.assertEqual(end_tag["signature_offsets"], {"122": 1, "126": 13})
        self.assertEqual(end_tag["bad_size"], 0)
        self.assertEqual(end_tag["bad_signature"], 0)
        self.assertEqual(end_tag["modified_mismatches"], 0)
        self.assertEqual(
            end_tag["time_relations"],
            {
                "created_time_a_exact": 11,
                "created_time_a_millis_close": 3,
                "created_time_b_exact": 11,
                "created_time_header_exact": 14,
                "display_created_time_exact": 11,
                "display_created_time_millis_close": 3,
                "display_modified_time_exact": 11,
                "last_recognised_data_modified_time_nonzero": 2,
                "extra_time_nonzero": 2,
                "modified_exact": 14,
            },
        )
        page_id = report["page_id_info_profiles"]
        self.assertEqual(page_id["parsed_files"], 14)
        self.assertEqual(page_id["records"], 114)
        self.assertEqual(page_id["bad_size"], 0)
        self.assertEqual(page_id["page_hash_sha256_matches"], 0)
        geometry = report["payload_geometry_profiles"]
        self.assertEqual(geometry["count"], 490)
        self.assertEqual(geometry["by_type"], {"image": 58, "shape": 424, "text_box": 8})
        self.assertEqual(
            geometry["point_counts"],
            {"1": 10, "10": 1, "12": 3, "15": 1, "2": 83, "3": 10, "4": 199, "5": 28, "6": 79, "7": 1, "8": 72, "9": 3},
        )
        self.assertEqual(
            geometry["marker_deltas"],
            [
                {"object_type": "image", "marker": "image", "l0_delta": 0, "l1_delta": 0, "count": 58},
                {"object_type": "shape", "marker": "shape", "l0_delta": 0, "l1_delta": 0, "count": 351},
                {"object_type": "text_box", "marker": "text", "l0_delta": 123, "l1_delta": 0, "count": 8},
            ],
        )
        self.assertEqual(
            geometry["shape_roles"],
            [
                {"shape_type": "arrow", "type_code": "None", "role": "shaft_endpoints", "count": 73},
                {"shape_type": "cross", "type_code": "17", "role": "frame_edge_midpoints", "count": 8},
                {"shape_type": "ellipse", "type_code": "1", "role": "outline_vertices", "count": 71},
                {"shape_type": "freeform", "type_code": "88", "role": "freeform_vertices", "count": 2},
                {"shape_type": "freeform", "type_code": "89", "role": "freeform_vertices", "count": 4},
                {"shape_type": "freeform_smooth", "type_code": "90", "role": "bezier_control_points", "count": 41},
                {"shape_type": "heart", "type_code": "23", "role": "bezier_control_points", "count": 5},
                {"shape_type": "hexagon", "type_code": "6", "role": "outline_vertices", "count": 36},
                {"shape_type": "pentagon", "type_code": "11", "role": "outline_vertices", "count": 6},
                {"shape_type": "rectangle", "type_code": "4", "role": "frame_edge_midpoints", "count": 48},
                {"shape_type": "rhombus", "type_code": "8", "role": "outline_vertices", "count": 24},
                {"shape_type": "rounded_rect", "type_code": "64", "role": "frame_edge_midpoints", "count": 6},
                {"shape_type": "star", "type_code": "13", "role": "outer_vertices", "count": 22},
                {"shape_type": "trapezoid", "type_code": "9", "role": "frame_edge_midpoints", "count": 37},
                {"shape_type": "triangle", "type_code": "2", "role": "vertices_with_edge_midpoints", "count": 41},
            ],
        )


class NoteDocStructuralTest(unittest.TestCase):
    """The sequential note.note parse must hold with zero counterexamples.

    `parse_note_doc` has a positional gate: it must consume `note.note` bytes
    `0 .. len-32` exactly (the trailing 32 bytes are the validated
    `sha256(note.note[:-32])`), so every field boundary in between must be
    correct for the parse to land on the hash. The cross-checks assert the
    structural parse agrees with the independent marker scans.
    """

    def test_note_doc_sequential_parse(self) -> None:
        require_sample(SAMPLES)

        report = collect_note_doc([SAMPLES])
        summary = report["summary"]

        self.assertEqual(summary["files"], 14)
        self.assertEqual(summary["parse_ok"], 14)
        self.assertEqual(summary["landed_on_hash"], 14)
        self.assertEqual(summary["header_matches_pysdocx"], 14)
        self.assertEqual(summary["gap_sizes"], {8: 12, 0: 2})
        self.assertEqual(summary["title_text_matches"], summary["title_text_surfaces"])
        self.assertEqual(summary["body_text_matches"], summary["body_text_surfaces"])
        self.assertEqual(summary["span_families_equal"], summary["span_families_total"])
        self.assertEqual(summary["inline_objects_with_anchor_match"], 3)
        self.assertEqual(summary["inline_object_surfaces"], 3)
        self.assertEqual(summary["cell_texts_match_table_scan"], 2)
        self.assertEqual(summary["cell_text_surfaces"], 2)
        self.assertEqual(summary["voice_records"], 2)
        self.assertEqual(summary["voice_all_fields_match"], 2)


class TextBoxLayoutRegressionTest(unittest.TestCase):
    def test_rotated_text_box_wrapping(self) -> None:
        require_sample(ONLY_TEXT_SQUARED)

        page_name = list_pages(ONLY_TEXT_SQUARED)[1]
        _name, page_data = load_page(ONLY_TEXT_SQUARED, page_name)
        page = parse_page(page_data)
        boxes = page["text_boxes"]

        self.assertEqual(len(boxes), 3)
        tilted = debug_text_box_layout(boxes[1], page_size=(page["width"], page["height"]))
        vertical = debug_text_box_layout(boxes[2], page_size=(page["width"], page["height"]))

        self.assertEqual(
            [line["text"] for line in tilted["lines"]],
            ["testo dentro una ", "casella di testo su ", "2 righe inclinata"],
        )
        self.assertEqual(
            [line["text"] for line in vertical["lines"]],
            [
                "testo dentro una casella di ",
                "testo in grassetto e in ",
                "corsivo ruotato di 90 gradi",
            ],
        )


if __name__ == "__main__":
    unittest.main()
