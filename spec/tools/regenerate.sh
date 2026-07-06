#!/usr/bin/env bash
# Regenerate the vendored Kaitai parsers in spec/generated/ from spec/ksy/.
# Run this after editing any .ksy so the test gate (tests/test_kaitai_spec.py)
# checks the current spec. Needs the Kaitai JS compiler + js-yaml.
#
#   npm install kaitai-struct-compiler js-yaml   # once, anywhere; set NODE_PATH
#   NODE_PATH=<that node_modules> spec/tools/regenerate.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/spec/generated"
mkdir -p "$OUT"
for ksy in "$ROOT"/spec/ksy/*.ksy; do
  node "$ROOT/spec/tools/compile_ksy.js" "$ksy" "$OUT"
done
echo "Regenerated parsers in $OUT"
echo "Now run: .venv/bin/python -m unittest tests.test_kaitai_spec"
