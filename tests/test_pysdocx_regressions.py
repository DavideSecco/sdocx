import unittest
from pathlib import Path

from pysdocx.container import list_pages, load_page
from pysdocx.inventory import build_inventory
from pysdocx.page import parse_page
from pysdocx.render import debug_text_box_layout


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
ONLY_TEXT_SQUARED = SAMPLES / "OnlyTextTypeWritten_squared_260703_013624.sdocx"


def require_sample(path: Path) -> None:
    if not path.exists():
        raise unittest.SkipTest(f"sample fixture not available: {path}")


class InventoryRegressionTest(unittest.TestCase):
    def test_note_tail_inventory_counts(self) -> None:
        require_sample(SAMPLES)

        report = build_inventory([SAMPLES])
        tail = report["note_tail_profiles"]
        coverage = tail["coverage"]

        self.assertEqual(report["sample_count"], 13)
        self.assertEqual(tail["kinds"]["tail_sentinel"], 13)
        self.assertEqual(tail["kinds"]["tail_hash_block"], 13)
        self.assertEqual(tail["kinds"]["pen_preload_path"], 38)
        self.assertEqual(tail["kinds"]["pen_preload_prelude"], 24)
        self.assertEqual(tail["kinds"]["pen_preload_prelude_raw"], 13)
        self.assertEqual(tail["kinds"]["pen_style_tail"], 10)
        self.assertEqual(tail["kinds"]["voice_clip"], 2)
        self.assertEqual(coverage["known_bytes"], 5938)
        self.assertEqual(coverage["unknown_bytes"], 0)
        self.assertEqual(
            tail["preload_prelude_params"],
            {
                "10;": 2,
                "13;": 3,
                "14;": 3,
                "18;0;100;": 4,
                "4;": 2,
                "5;": 2,
                "7;": 1,
                "8;": 7,
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
            {"page_id_head_exact": 10, "page_id_head_shifted_u32_2": 3},
        )
        media = report["media_info_profiles"]
        self.assertEqual(media["parsed_files"], 13)
        self.assertEqual(media["records"], 60)
        self.assertEqual(media["magic"], {"0x1452": 1, "0x1518": 12})
        self.assertEqual(media["tail_tags"], {"1": 54, "20": 1, "3": 4, "5": 1})
        self.assertEqual(media["sha_mismatches"], 0)
        self.assertEqual(media["missing_media"], 0)
        self.assertEqual(media["unlisted_media"], 0)
        self.assertEqual(media["bad_eof"], 0)
        end_tag = report["end_tag_profiles"]
        self.assertEqual(end_tag["parsed_files"], 13)
        self.assertEqual(end_tag["payload_sizes"], {"142": 1, "146": 12})
        self.assertEqual(end_tag["format_versions"], {"4000": 9, "5400": 4})
        self.assertEqual(end_tag["signature_offsets"], {"122": 1, "126": 12})
        self.assertEqual(end_tag["bad_size"], 0)
        self.assertEqual(end_tag["bad_signature"], 0)
        self.assertEqual(end_tag["modified_mismatches"], 0)
        self.assertEqual(
            end_tag["time_relations"],
            {
                "created_time_a_exact": 10,
                "created_time_a_millis_close": 3,
                "created_time_b_exact": 10,
                "created_time_header_exact": 13,
                "extra_time_nonzero": 2,
                "modified_exact": 13,
            },
        )
        page_id = report["page_id_info_profiles"]
        self.assertEqual(page_id["parsed_files"], 13)
        self.assertEqual(page_id["records"], 48)
        self.assertEqual(page_id["bad_size"], 0)
        self.assertEqual(page_id["page_hash_sha256_matches"], 0)
        geometry = report["payload_geometry_profiles"]
        self.assertEqual(geometry["count"], 412)
        self.assertEqual(geometry["by_type"], {"image": 15, "shape": 390, "text_box": 7})
        self.assertEqual(
            geometry["point_counts"],
            {"1": 8, "10": 1, "12": 3, "15": 1, "2": 58, "3": 8, "4": 154, "5": 28, "6": 75, "7": 1, "8": 72, "9": 3},
        )
        self.assertEqual(
            geometry["marker_deltas"],
            [
                {"object_type": "image", "marker": "image", "l0_delta": 0, "l1_delta": 0, "count": 15},
                {"object_type": "shape", "marker": "shape", "l0_delta": 0, "l1_delta": 0, "count": 337},
                {"object_type": "text_box", "marker": "text", "l0_delta": 123, "l1_delta": 0, "count": 7},
            ],
        )
        self.assertEqual(
            geometry["shape_roles"],
            [
                {"shape_type": "arrow", "type_code": "None", "role": "shaft_endpoints", "count": 53},
                {"shape_type": "cross", "type_code": "17", "role": "frame_edge_midpoints", "count": 8},
                {"shape_type": "ellipse", "type_code": "1", "role": "outline_vertices", "count": 71},
                {"shape_type": "freeform", "type_code": "88", "role": "freeform_vertices", "count": 1},
                {"shape_type": "freeform", "type_code": "89", "role": "freeform_vertices", "count": 4},
                {"shape_type": "freeform_smooth", "type_code": "90", "role": "bezier_control_points", "count": 32},
                {"shape_type": "heart", "type_code": "23", "role": "bezier_control_points", "count": 5},
                {"shape_type": "hexagon", "type_code": "6", "role": "outline_vertices", "count": 36},
                {"shape_type": "pentagon", "type_code": "11", "role": "outline_vertices", "count": 6},
                {"shape_type": "rectangle", "type_code": "4", "role": "frame_edge_midpoints", "count": 48},
                {"shape_type": "rhombus", "type_code": "8", "role": "outline_vertices", "count": 24},
                {"shape_type": "rounded_rect", "type_code": "64", "role": "frame_edge_midpoints", "count": 6},
                {"shape_type": "star", "type_code": "13", "role": "outer_vertices", "count": 22},
                {"shape_type": "trapezoid", "type_code": "9", "role": "frame_edge_midpoints", "count": 37},
                {"shape_type": "triangle", "type_code": "2", "role": "vertices_with_edge_midpoints", "count": 37},
            ],
        )


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
