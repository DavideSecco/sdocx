import unittest
import zipfile
from pathlib import Path

from pysdocx.container import list_pages, load_page
from pysdocx.note_doc import note_doc_common_frames, parse_note_doc
from pysdocx.page import (_parse_object_header, page_background_color, page_template,
                         page_thumbnail_media_index, parse_page, parse_page_tree)
from pysdocx.render import debug_text_box_layout
from tests.golden import compute_reports, corpus_snapshot, load_golden


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
ONLY_TEXT_SQUARED = SAMPLES / "OnlyTextTypeWritten_squared_260703_013624.sdocx"
MATH_WEB = SAMPLES / "Mathsolver&Hyperlink_260711_180442.sdocx"
# Every sample contributes exactly one end_tag.bin/mediaInfo.dat/pageIdInfo.dat/note.note, so
# "how many of the corpus files exhibit this per-file structural fact" is definitionally the
# sample count, not a number to hand-update each time a sample is added.
SAMPLE_COUNT = len(list(SAMPLES.glob("*.sdocx")))

REGEN_HINT = (
    "corpus fingerprint changed. If this is an intentional sample add or decoder change, "
    "regenerate it:  .venv/bin/python -m tests.regen_golden  (then review the JSON diff)."
)


def require_sample(path: Path) -> None:
    if not path.exists():
        raise unittest.SkipTest(f"sample fixture not available: {path}")


class CorpusProfileTest(unittest.TestCase):
    """Corpus-wide regression, split into invariants (always true) + a golden fingerprint.

    `test_invariants` asserts the corpus-*independent* truths: every file parses, the note.note
    note.note parses sequentially through every flex field to its trailing hash, with no
    sha/eof/size/signature corruption,
    per-file counts equal the sample count, and every "matches" equals its "surfaces". It also
    exercises the note.note sequential-parse gate — `parse_note_doc` must consume `note.note`
    bytes `0 .. len-32` exactly (the trailing 32 are `sha256(note.note[:-32])`), so landing on
    the hash on every file proves every field boundary is correct.

    `test_snapshot_matches_golden` compares the corpus-*dependent* counts against
    `tests/golden/corpus_profiles.json` (see tests/golden.py) — adding a sample or changing a
    decoder means rerunning `python -m tests.regen_golden`, not hand-editing dozens of numbers.
    Both share one `compute_reports()` call in setUpClass (the reports are expensive)."""

    @classmethod
    def setUpClass(cls) -> None:
        require_sample(SAMPLES)
        cls.inventory, cls.leads, cls.notedoc = compute_reports()

    def test_snapshot_matches_golden(self) -> None:
        actual = corpus_snapshot(self.inventory, self.leads, self.notedoc)
        golden = load_golden()
        self.assertEqual(set(actual), set(golden), REGEN_HINT)
        for section in sorted(actual):
            with self.subTest(section=section):
                self.assertEqual(actual[section], golden[section], f"[{section}] {REGEN_HINT}")

    def test_invariants(self) -> None:
        inventory, leads, notedoc = self.inventory, self.leads, self.notedoc

        # sdocx2pdf leads: no unexpected end_tag variants, no page-level audio objects.
        self.assertEqual(leads["end_tag_files"], SAMPLE_COUNT)
        self.assertEqual(
            leads["end_tag_variant_gaps"],
            {
                "nonzero_property_flags": 0,
                "landscape": 0,
                "nonempty_sdk_strings": 0,
                "skipped_blocks": 0,
                "encryption_blocks": 0,
            },
        )
        self.assertEqual(leads["page_audio_type10_objects"], 0)

        # The legacy marker-based note-tail scan is a diagnostic only and is superseded by the
        # exact sequential parser below. New flex layouts (e.g. COEDIT) need not resemble its old
        # sentinel/hash windows, so do not make those scan artifacts corpus invariants.
        self.assertEqual(inventory["sample_count"], SAMPLE_COUNT)

        # mediaInfo: one record set per file, every SHA verifies, no missing/unlisted/bad-eof.
        media = inventory["media_info_profiles"]
        self.assertEqual(media["parsed_files"], SAMPLE_COUNT)
        self.assertEqual(media["sha_mismatches"], 0)
        self.assertEqual(media["missing_media"], 0)
        self.assertEqual(media["unlisted_media"], 0)
        self.assertEqual(media["bad_eof"], 0)

        # end_tag: one per file, no bad size/signature, header/modified time always exact.
        end_tag = inventory["end_tag_profiles"]
        self.assertEqual(end_tag["parsed_files"], SAMPLE_COUNT)
        self.assertEqual(end_tag["bad_size"], 0)
        self.assertEqual(end_tag["bad_signature"], 0)
        self.assertEqual(end_tag["modified_mismatches"], 0)
        self.assertEqual(end_tag["time_relations"]["created_time_header_exact"], SAMPLE_COUNT)
        self.assertEqual(end_tag["time_relations"]["modified_exact"], SAMPLE_COUNT)

        # pageIdInfo: one per file, no bad size (the manifest hash is a mirrored footer hash, not
        # a sha256 of the member — so page_hash_sha256_matches is expected to be 0, see page.py).
        page_id = inventory["page_id_info_profiles"]
        self.assertEqual(page_id["parsed_files"], SAMPLE_COUNT)
        self.assertEqual(page_id["bad_size"], 0)
        self.assertEqual(page_id["page_hash_sha256_matches"], 0)

        # note.note sequential parse: lands on the trailing hash on every file (proves boundaries),
        # and every scan-vs-structural cross-check agrees (matches == surfaces, zero errors).
        self.assertEqual(notedoc["files"], SAMPLE_COUNT)
        self.assertEqual(notedoc["parse_ok"], SAMPLE_COUNT)
        self.assertEqual(notedoc["landed_on_hash"], SAMPLE_COUNT)
        self.assertEqual(notedoc["header_matches_pysdocx"], SAMPLE_COUNT)
        self.assertEqual(notedoc["title_text_matches"], notedoc["title_text_surfaces"])
        self.assertEqual(notedoc["body_text_matches"], notedoc["body_text_surfaces"])
        self.assertEqual(notedoc["span_families_equal"], notedoc["span_families_total"])
        self.assertEqual(notedoc["inline_objects_with_anchor_match"], notedoc["inline_object_surfaces"])
        self.assertEqual(notedoc["cell_texts_match_table_scan"], notedoc["cell_text_surfaces"])
        self.assertEqual(notedoc["tables_structural"], notedoc["tables_structural_all_checks"])
        self.assertEqual(notedoc["table_structural_errors"], 0)
        self.assertEqual(notedoc["voice_all_fields_match"], notedoc["voice_records"])


class MathSolverWebRegressionTest(unittest.TestCase):
    def test_web_inline_object_and_math_uuid_property(self) -> None:
        require_sample(MATH_WEB)
        with zipfile.ZipFile(MATH_WEB) as z:
            note = z.read("note.note")
            doc = parse_note_doc(note)
            body = note_doc_common_frames(note, doc)["body"]
            web = [o for o in body["inline"]["objects"] if o["object_type"] == 13]
            self.assertEqual(len(web), 1)
            self.assertEqual(web[0]["position"], body["text"].index("\ufffc"))

            page_name = next(n for n in z.namelist() if n.endswith(".page") and len(z.read(n)) > 1000)
            page_data = z.read(page_name)
        base = parse_page(page_data)["base"]
        tree = parse_page_tree(page_data, 0, 0, base)
        props = []
        for obj in tree["layers"][0]["objects"]:
            header = _parse_object_header(page_data[obj["blob_off"]:obj["end"]])
            if header and header.get("extra_key_block"):
                props.append(header["extra_key_block"])
        arrays = [p for p in props if p["key"] == "RecogUIFeature_MathStrokeUuidStringArray"]
        self.assertTrue(arrays)
        self.assertTrue(all(p["value_kind"] == "utf16_string_array" for p in arrays))
        self.assertTrue(all(p["strings"] for p in arrays))


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


class PageBackgroundColorTest(unittest.TestCase):
    """The paper color is a per-.page field (RE 2026-07-09), located by signature.

    Every page of a note carries the same single light paper; the pink `Rosina`
    one-variable sample pins the field. Also asserts the whole corpus resolves a
    color on every page (no None) — the old fixed-offset heuristic missed some.
    """

    TEST_BG = SAMPLES / "test-background"

    def test_paper_color_from_one_variable_samples(self) -> None:
        cases = {
            "Default-Liscio_260709_125314.sdocx": (252, 252, 252),
            "Bianca-Liscio_260709_125449.sdocx": (230, 230, 230),
            "Rosina-Liscio_260709_125531.sdocx": (245, 221, 221),
            "Bianca-quadretti_260709_125637.sdocx": (230, 230, 230),
            # Explicit DARK paper is the same field, a dark RGB — the note's paper,
            # not a theme flag (fixed_background_theme stays 2 here).
            "Nera-Liscio_260709_140421.sdocx": (1, 1, 1),
        }
        checked = 0
        for name, expected in cases.items():
            path = self.TEST_BG / name
            if not path.exists():
                continue
            import zipfile

            with zipfile.ZipFile(path) as z:
                for pn in list_pages(path):
                    self.assertEqual(page_background_color(z.read(pn)), expected, f"{name} {pn}")
                    checked += 1
        if checked == 0:
            self.skipTest("test-background samples not available")

    def test_every_corpus_page_resolves_a_paper_color(self) -> None:
        require_sample(SAMPLES)
        import zipfile

        for sdocx in sorted(SAMPLES.glob("*.sdocx")):
            with zipfile.ZipFile(sdocx) as z:
                for pn in list_pages(sdocx):
                    self.assertIsNotNone(
                        page_background_color(z.read(pn)), f"{sdocx.name} {pn}"
                    )


class PdfTemplateLinkTest(unittest.TestCase):
    """PDF-backed templates (Academic multi-page + imported PDF) reference an embedded
    `media/….pdf` by (media index, 0-based page index). See page_pdf_template / the
    "PDF-backed templates" section of docs/format/container/page/README.md.
    """

    NOTEBOOK = SAMPLES / "Notebook&Planner1_260709_213306.sdocx"

    def test_notebook_pages_reference_embedded_pdfs(self) -> None:
        require_sample(self.NOTEBOOK)
        import zipfile

        with zipfile.ZipFile(self.NOTEBOOK) as z:
            refs = [page_template(z.read(pn)) for pn in list_pages(self.NOTEBOOK)]

        # Every page is PDF-backed; identity is (media index, page index), never a Basic id/name.
        self.assertTrue(all(t and t["kind"] == "pdf" and t["name"] is None for t in refs))
        # StudyTemplates @ media 0 uses 0-based indices 0..6 (7-page PDF: 1 content + 6 template);
        # PlannerTemplates @ media 2 uses 0..5 (6-page PDF), with page 5 referenced twice.
        media0 = sorted(t["pdf_page_index"] for t in refs if t["pdf_media_index"] == 0)
        media2 = sorted(t["pdf_page_index"] for t in refs if t["pdf_media_index"] == 2)
        self.assertEqual(media0, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(media2, [0, 1, 2, 3, 4, 5, 5])
        # Both PDFs are actually present in the archive.
        with zipfile.ZipFile(self.NOTEBOOK) as z:
            pdfs = {n for n in z.namelist() if n.endswith(".pdf")}
        self.assertTrue(any("0@" in n for n in pdfs) and any("2@" in n for n in pdfs))

    def test_imported_pdf_page_is_not_a_basic_template(self) -> None:
        quiz = SAMPLES / "quiz.sdocx"
        require_sample(quiz)
        import zipfile

        with zipfile.ZipFile(quiz) as z:
            pn = list_pages(quiz)[0]
            t = page_template(z.read(pn))
        # Regression: this imported-PDF page used to be mislabelled as the Basic "Lined (narrow)".
        self.assertEqual(t["kind"], "pdf")
        self.assertEqual((t["pdf_media_index"], t["pdf_page_index"]), (0, 0))

    def test_rasterises_embedded_template_page(self) -> None:
        """The decoded (media, page) link drives faithful rasterisation of the embedded PDF."""
        require_sample(self.NOTEBOOK)
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            self.skipTest("pypdfium2 not installed (optional render dependency)")
        from pysdocx.container import load_media_by_index
        from pysdocx.render import rasterize_pdf_page

        media = load_media_by_index(self.NOTEBOOK, 0)  # 07_StudyTemplates_A4_v2.pdf, 7 pages
        self.assertIsNotNone(media)
        raster = rasterize_pdf_page(media[1], 0, 1600)
        # A4 page rasterised to ~1600 wide -> full RGBA background at the page's ~1.415 aspect
        # (pdfium rounds scale*width, so allow a pixel of slack), tall enough to fill the page.
        self.assertAlmostEqual(raster.shape[1], 1600, delta=2)
        self.assertEqual(raster.shape[2], 4)
        self.assertGreater(raster.shape[0], 2200)
        # Out-of-range page index degrades to None rather than raising.
        self.assertIsNone(rasterize_pdf_page(media[1], 999, 1600))


class CustomImageTemplateTest(unittest.TestCase):
    SAMPLE = SAMPLES / "PagLiscia&templatescustoms_260711_122117.sdocx"
    BBOX_SAMPLE = SAMPLES / "PaginaVuota&Paginapuntino_260711_122434.sdocx"

    def test_custom_uri_resolves_to_embedded_image(self) -> None:
        require_sample(self.SAMPLE)
        import zipfile

        with zipfile.ZipFile(self.SAMPLE) as z:
            pages = list_pages(self.SAMPLE)
            templates = [page_template(z.read(pn)) for pn in pages]
            names = z.namelist()
        self.assertIsNone(templates[0])  # plain page
        custom = templates[1]
        self.assertEqual((custom["kind"], custom["source"]), ("image", "custom_image"))
        self.assertEqual(custom["name"], "files_231229_092644_140.jpg")
        self.assertTrue(any(n.endswith("@" + custom["name"]) for n in names))
        self.assertTrue(all(t and t["kind"] == "pdf" for t in templates[2:]))

    def test_empty_vs_dot_control_has_one_serialized_stroke(self) -> None:
        require_sample(self.BBOX_SAMPLE)
        import zipfile
        from pysdocx.page import _locate_paper_record

        with zipfile.ZipFile(self.BBOX_SAMPLE) as z:
            pages = [z.read(pn) for pn in list_pages(self.BBOX_SAMPLE)]
        self.assertEqual([parse_page(p)["object_count"] for p in pages], [0, 1, 0])
        self.assertEqual([_locate_paper_record(p) for p in pages], [0x84, 0xA4, 0x84])


class PageThumbnailLinkTest(unittest.TestCase):
    def test_plain_page_thumbnail_indices_resolve_to_spi_media(self) -> None:
        import zipfile
        from pysdocx.container import parse_media_info

        checked = 0
        for sample in sorted(SAMPLES.glob("*.sdocx")):
            with zipfile.ZipFile(sample) as z:
                media = {
                    r["media_index"]: r["name"]
                    for r in parse_media_info(z.read("media/mediaInfo.dat"))["records"]
                }
                for page_name in list_pages(sample):
                    index = page_thumbnail_media_index(z.read(page_name))
                    if index is None:
                        continue
                    self.assertTrue(media.get(index, "").endswith(".spi"), (sample.name, page_name, index))
                    checked += 1
        self.assertEqual(checked, 30)


if __name__ == "__main__":
    unittest.main()
