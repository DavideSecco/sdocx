#!/usr/bin/env bash
# Build the WASM package for the static viewer into viewer/pkg.
# Run from anywhere — paths are resolved relative to this script, so the
# output always lands in the repo-root viewer/pkg (not a crate-relative one).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
exec wasm-pack build "$root/crates/sdocx-wasm" \
  --target web --out-name sdocx --out-dir "$root/viewer/pkg"
