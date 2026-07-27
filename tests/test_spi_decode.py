"""Regression gate for the `.spi` (Samsung "Maetel" raster) decoder.

The decoder was reverse-engineered against Samsung's own `libSPenBase.so` run
under emulation, and verified byte-identical to it on **every** `.spi` member of
the corpus -- 220 members, 800,698,496 pixels, zero differing pixels. That
verification needs the Samsung binary, so it cannot run here.

What runs here is its committed residue: the members that live in the *tracked*
part of the corpus, pinned by the SHA-256 of their decoded RGBA. Those hashes
were taken from decodes that had just been proven identical to the native
decoder, so a mismatch means our decoder changed behaviour -- and with no
Samsung binary, no emulator and no network in the loop.

Regenerate deliberately (never to "fix" a red test you have not explained):

    .venv/bin/python -m tests.regen_spi_golden
"""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "spi_members.json"

# Only samples committed to the repo: the rest of the corpus is the user's
# private notes and is not available to a fresh clone.
TRACKED_SAMPLES = ("cs61bl_su22", "handwritten", "quiz")


def tracked_members():
    """(key, path, member name) for every `.spi` in the tracked samples."""
    from pysdocx.spi.parse import iter_member_bytes

    for sample in TRACKED_SAMPLES:
        path = ROOT / "samples" / sample / "note.sdocx"
        if not path.exists():
            continue
        for name, data in iter_member_bytes(path):
            yield f"{sample}/{name}", path, name, data


def digest(data: bytes) -> dict:
    from pysdocx.spi import decode_rgba

    rgba, width, height = decode_rgba(data)
    return {"width": width, "height": height,
            "sha256": hashlib.sha256(rgba).hexdigest()}


def compute_snapshot() -> dict:
    return {key: digest(data) for key, _p, _n, data in tracked_members()}


class SpiDecodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN_PATH.exists():
            raise unittest.SkipTest(f"{GOLDEN_PATH.name} missing")
        cls.golden = json.loads(GOLDEN_PATH.read_text())
        cls.members = list(tracked_members())
        if not cls.members:
            raise unittest.SkipTest("no tracked samples with .spi members")

    def test_every_tracked_member_is_covered(self):
        """A sample that stops being decoded must fail, not silently vanish."""
        self.assertEqual(sorted(k for k, *_ in self.members), sorted(self.golden),
                         "the tracked .spi members changed; rerun tests.regen_spi_golden")

    def test_pixels_match_the_golden_digest(self):
        """Byte-for-byte: the decoded RGBA hashes to what the native decoder produced."""
        for key, _path, _name, data in self.members:
            with self.subTest(member=key):
                want = self.golden[key]
                got = digest(data)
                self.assertEqual(got["width"], want["width"])
                self.assertEqual(got["height"], want["height"])
                self.assertEqual(got["sha256"], want["sha256"],
                                 f"{key}: decoded pixels differ from the golden digest")

    def test_static_tables_are_pure_data(self):
        """`tables.py` must stay constants: no imports, no calls, no file reads.

        Asserted on the parsed module rather than on its text -- the docstring
        legitimately names the Samsung library when explaining how the tables
        were extracted. What must never come back is *code* that goes looking
        for it at runtime.
        """
        import ast

        from pysdocx.spi import tables

        tree = ast.parse(Path(tables.__file__).read_text())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertEqual(imports, [], "the generated tables must not import anything")
        self.assertEqual(calls, [], "the generated tables must not call anything")
        self.assertEqual(len(tables.SCANS), 12)
        self.assertEqual(len(tables.SHIFT_MATRIX), 52)


if __name__ == "__main__":
    unittest.main()
