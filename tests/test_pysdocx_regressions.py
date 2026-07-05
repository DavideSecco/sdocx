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
        self.assertEqual(tail["pen_style_tail_params"], {"5;": 1, "8;": 2})
        self.assertEqual(
            tail["page_id_info_relations"],
            {"page_id_head_exact": 10, "page_id_head_shifted_u32_2": 3},
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
