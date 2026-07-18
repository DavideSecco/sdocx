#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out_dir="${TMPDIR:-/tmp}/sdocx-ksv"
mkdir -p "$out_dir"

usage() {
  cat <<'EOF'
Usage:
  spec/tools/ksv_quickstart.sh page-id
  spec/tools/ksv_quickstart.sh end-tag
  spec/tools/ksv_quickstart.sh media-info
  spec/tools/ksv_quickstart.sh page
  spec/tools/ksv_quickstart.sh note

Opens small, known-good sample members in Kaitai Struct Visualizer without
changing your current shell directory.
EOF
}

run_ksv() {
  local sample="$1"
  local member="$2"
  local target="$3"
  local spec="$4"

  unzip -p "$repo_root/$sample" "$member" > "$out_dir/$target"
  ksv "$out_dir/$target" "$repo_root/spec/ksy/$spec"
}

case "${1:-}" in
  page-id)
    run_ksv \
      "samples/OnlyPensBlacksize10_260630_120309/note.sdocx" \
      "pageIdInfo.dat" \
      "pageIdInfo.dat" \
      "sdocx_page_id_info.ksy"
    ;;
  end-tag)
    run_ksv \
      "samples/OnlyPensBlacksize10_260630_120309/note.sdocx" \
      "end_tag.bin" \
      "end_tag.bin" \
      "sdocx_end_tag.ksy"
    ;;
  media-info)
    run_ksv \
      "samples/OnlyImages_260702_190147/note.sdocx" \
      "media/mediaInfo.dat" \
      "mediaInfo.dat" \
      "sdocx_media_info.ksy"
    ;;
  page)
    run_ksv \
      "samples/OnlyPensBlacksize10_260630_120309/note.sdocx" \
      "4302b93e-746a-11f1-9552-b7833a8a74d9.page" \
      "OnlyPens.page" \
      "sdocx_page.ksy"
    ;;
  note)
    run_ksv \
      "samples/OnlyPensBlacksize10_260630_120309/note.sdocx" \
      "note.note" \
      "note.note" \
      "sdocx_note.ksy"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
