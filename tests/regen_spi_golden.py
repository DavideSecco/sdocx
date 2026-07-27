"""Regenerate tests/golden/spi_members.json from the tracked samples.

    .venv/bin/python -m tests.regen_spi_golden

Run this only when a `.spi` decoder change is *explained* -- and, if the Samsung
binary is at hand, after `apk-re/scripts/spi_corpus_pixels.py` has confirmed the
new output is still byte-identical to the native decoder on the whole corpus.
Blessing a hash you cannot explain throws away the only protection this gate
gives.
"""
import json

from tests.test_spi_decode import GOLDEN_PATH, compute_snapshot


def main() -> None:
    snapshot = compute_snapshot()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN_PATH} ({len(snapshot)} members)")


if __name__ == "__main__":
    main()
