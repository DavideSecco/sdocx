"""Regenerate tests/golden/corpus_profiles.json from the current samples/ corpus.

Run after adding or removing a sample, or when a decoder change legitimately alters the corpus
fingerprint:

    .venv/bin/python -m tests.regen_golden

Then review the JSON diff before committing — an *unexpected* change is a regression, not a
number to bless. The corpus-independent invariants are checked separately (and always) by
CorpusProfileTest.test_invariants, so they can't be silently regenerated away.
"""
from tests.golden import GOLDEN_PATH, compute_reports, corpus_snapshot, save_golden


def main() -> None:
    snapshot = corpus_snapshot(*compute_reports())
    save_golden(snapshot)
    print(f"wrote {GOLDEN_PATH}")


if __name__ == "__main__":
    main()
