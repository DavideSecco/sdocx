"""CLI entry point: python -m pysdocx <command> ..."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pysdocx.container import list_attachments, list_media_info, list_pages, load_note, load_page, load_page_id_info
from pysdocx.dump import dump_container
from pysdocx.ink import color_hex
from pysdocx.inventory import build_inventory
from pysdocx.note import annotate_note_tail_with_page_id_info, parse_note_metadata, parse_typed_text
from pysdocx.page import parse_page


def cmd_dump(args: argparse.Namespace) -> None:
    print(dump_container(args.file))


def _fmt_color(color: tuple[int, int, int] | None) -> str:
    return color_hex(color) or "(default)"


def _fmt_bbox(bbox: tuple[float, float, float, float]) -> str:
    return f"({bbox[0]:.1f},{bbox[1]:.1f})-({bbox[2]:.1f},{bbox[3]:.1f})"


def _fmt_optional_bbox(bbox: tuple[float, float, float, float] | None) -> str:
    return _fmt_bbox(bbox) if bbox is not None else "(none)"


def _preview(text: str, limit: int = 72) -> str:
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _fmt_range(item: dict) -> str:
    return f"{item['start']}..{item['end']}"


def _style_flags(style: tuple) -> str:
    flags = []
    if style[0]:
        flags.append("bold")
    if style[1]:
        flags.append("italic")
    if style[2]:
        flags.append("underline")
    if style[3]:
        flags.append("strike")
    if style[4]:
        flags.append(f"color={_fmt_color(style[4])}")
    if style[5]:
        flags.append(f"highlight={_fmt_color(style[5])}")
    if style[6]:
        flags.append(f"font={style[6]:.2f}")
    return ", ".join(flags) if flags else "plain"


def cmd_stroke_table(args: argparse.Namespace) -> None:
    page_names = list_pages(args.file)
    if args.page:
        page_names = [p for p in page_names if args.page in p]
        if not page_names:
            print(f"no .page file matches {args.page!r}", file=sys.stderr)
            sys.exit(1)

    any_mismatch = False
    for page_name in page_names:
        _, page_data = load_page(args.file, page_name)
        result = parse_page(page_data)
        short = result["uuid"][:8]
        mismatch = result["kept"] != result["stroke_count"]
        any_mismatch |= mismatch
        flag = "  MISMATCH" if mismatch else ""
        print(
            f"{short}  stroke_count={result['stroke_count']:>4}  "
            f"attempted={result['attempted']:>4}  kept={result['kept']:>4}{flag}"
        )

        if args.detail:
            print(
                f"  {'idx':>4} {'extra':>5} {'layout':>8} {'n_pts':>6} {'width':>7} "
                f"{'tool':>4} {'color':>8} {'bbox':<32} {'outcome'}"
            )
            for a in result["attempts"]:
                tool = a["tool_id"] if a["tool_id"] is not None else "?"
                print(
                    f"  {a['idx']:>4} {a['extra_len']:>5} {a['layout']:>8} "
                    f"{a['n_points_decoded']:>6} {a['pen_width']:>7.2f} "
                    f"{str(tool):>4} {_fmt_color(a['color']):>8} "
                    f"{_fmt_bbox(a['bbox']):<32} {a['outcome']}"
                )

    if any_mismatch:
        sys.exit(1)


def _print_object(obj: dict, depth: int, detail: bool, media_by_object: dict[int, list[dict]] | None = None) -> None:
    header = obj["header"] or {}
    indent = "  " * depth
    uuid = header.get("uuid", "")
    uuid_short = uuid[:8] if uuid else "-"
    print(
        f"{indent}{obj['idx']:>4} raw={obj['raw_type']:<3} type={obj['type']:<14} "
        f"size={obj['size']:>5} child={obj['child_count']:<3} off=0x{obj['off']:x} "
        f"bbox={_fmt_optional_bbox(obj['bbox'])} uuid={uuid_short}"
    )
    if detail and header:
        profile = obj.get("header_profile") or {}
        print(
            f"{indent}     header total={header['total_size']} var={header['var_data_offset']} "
            f"fmt={header['format_version']} flags=0x{header['flags']:x} "
            f"field=0x{header['field_flags']:x} mtime={header['modified_time']} "
            f"profile={profile.get('signature', '-')}/{profile.get('family', '-')}"
        )
        if profile.get("known_features") or profile.get("unknown_bits"):
            print(
                f"{indent}     header_features known={profile.get('known_features', [])} "
                f"unknown_bits={profile.get('unknown_bits', [])}"
            )
        ext = header.get("ext_block")
        if ext:
            print(
                f"{indent}     ext_block off={ext['off']} counter={ext['counter']} "
                f"seq={ext['seq']} page={ext['page_width']}x{ext['page_height']}"
            )
        extra_key = header.get("extra_key_block")
        if extra_key:
            print(
                f"{indent}     extra_key_block off={extra_key['off']} head={extra_key['head']} "
                f"head_ok={extra_key['head_ok']} key_len={extra_key['key_len']} "
                f"key={extra_key['key']!r} trailing={extra_key['trailing']}"
            )
    if detail and media_by_object:
        for media in media_by_object.get(obj["off"], []):
            print(
                f"{indent}     media index={media['media_index']} "
                f"index_off=0x{media['media_index_off']:x} size={media['media_index_size']} "
                f"marker_off=0x{media['off']:x}"
            )
    for child in obj["children"]:
        _print_object(child, depth + 1, detail, media_by_object)


def _iter_cli_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        yield from _iter_cli_objects(obj["children"])


def _print_attachments(attachments: list[dict]) -> None:
    """List document-level media attachments (images/audio/sticky-memos) not tied to any page.

    Verified on a dedicated GT sample that sticky-note/audio pages have a completely empty
    object tree — so these can't be found by walking pages; list_attachments reads them
    straight from the archive's media/ entries instead.
    """
    if not attachments:
        return
    print("attachments (not necessarily placed on any page):")
    for att in sorted(attachments, key=lambda a: a["index"]):
        print(f"  [{att['index']}] {att['kind']:<11} {att['size']:>10,}B  {att['name']}")


def _print_object_summary(page_results: list[dict]) -> None:
    counts = Counter()
    header_counts = Counter()
    header_profiles = Counter()
    total_objects = 0
    total_strokes = 0
    total_kept = 0
    total_sticky_notes = 0
    total_attachment_placements = 0
    for result in page_results:
        total_objects += result["object_count"]
        total_strokes += result["stroke_count"]
        total_kept += result["kept"]
        total_sticky_notes += len(result["sticky_notes"])
        total_attachment_placements += len(result.get("attachment_placements", ()))
        for layer in result["layers"]:
            for obj in _iter_cli_objects(layer["objects"]):
                counts[(obj["raw_type"], obj["type"])] += 1
                header = obj["header"]
                if header:
                    header_counts[(obj["raw_type"], obj["type"], header["total_size"], header["field_flags"])] += 1
                profile = obj.get("header_profile")
                if profile:
                    header_profiles[(obj["type"], profile["family"], profile["signature"])] += 1

    print(f"summary pages={len(page_results)} objects={total_objects} strokes={total_strokes} kept={total_kept}")
    for (raw_type, obj_type), count in sorted(counts.items()):
        print(f"  raw={raw_type:<3} type={obj_type:<14} count={count}")
        for (hraw, htype, total_size, field_flags), header_count in sorted(header_counts.items()):
            if (raw_type, obj_type) == (hraw, htype):
                print(f"      header total={total_size:<4} field=0x{field_flags:x} count={header_count}")
    if header_profiles:
        print("  header profiles:")
        for (obj_type, family, signature), count in sorted(header_profiles.items()):
            print(f"      type={obj_type:<14} family={family:<16} sig={signature:<12} count={count}")
    if total_attachment_placements:
        print(f"  attachment_placements (outside declared object count) count={total_attachment_placements}")
    if total_sticky_notes:
        print(f"  sticky_note_ref (outside declared object count) count={total_sticky_notes}")


def cmd_objects(args: argparse.Namespace) -> None:
    page_names = list_pages(args.file)
    if args.page:
        page_names = [p for p in page_names if args.page in p]
        if not page_names:
            print(f"no .page file matches {args.page!r}", file=sys.stderr)
            sys.exit(1)

    page_results = []
    for page_name in page_names:
        _, page_data = load_page(args.file, page_name)
        page_results.append(parse_page(page_data))
    attachments = list_attachments(args.file)

    if args.summary:
        _print_object_summary(page_results)
        _print_attachments(attachments)
        return

    for page_idx, result in enumerate(page_results, 1):
        print(
            f"{page_idx:>2}. {result['uuid'][:8]}  layers={len(result['layers'])}  "
            f"objects={result['object_count']}  strokes={result['stroke_count']}  kept={result['kept']}"
        )
        for layer in result["layers"]:
            media_by_object = defaultdict(list)
            for placement in result["images"] + result["drawings"]:
                media_by_object[placement["object_off"]].append(placement)
            current = " current" if layer["current"] else ""
            print(
                f"  layer {layer['idx']}{current} uuid={layer['uuid'][:8] or '-'} "
                f"objects={layer['object_count']} flags=0x{layer['content_flags']:02x}"
            )
            for obj in layer["objects"]:
                _print_object(obj, 2, args.detail, media_by_object)
        for note in result["sticky_notes"]:
            print(
                f"     sticky_note_ref media={note['media_index']} "
                f"bbox={_fmt_bbox(note['bbox'])} off=0x{note['off']:x}  "
                f"(found via whole-page scan — outside this page's declared object count)"
            )
        for placement in result.get("attachment_placements", ()):
            print(
                f"     attachment_ref kind={placement['kind']} media={placement['media_index']} "
                f"type_tag={placement.get('type_tag')} bbox={_fmt_optional_bbox(placement.get('bbox'))} "
                f"off=0x{placement['off']:x} keys={placement.get('keys', [])}"
            )

    _print_attachments(attachments)


def _paragraph_is_default(paragraph: dict) -> bool:
    return (
        paragraph.get("alignment") == "left"
        and not paragraph.get("indent")
        and paragraph.get("style") is None
        and paragraph.get("line_spacing") is None
        and paragraph.get("list") is None
    )


def _print_typed_text_debug(parsed: dict, show_all_paragraphs: bool) -> None:
    text = parsed["text"]
    paragraphs = parsed.get("paragraphs") or []
    print(
        f"typed_text chars={len(text)} paragraphs={len(text.splitlines())} "
        f"runs={len(parsed.get('runs', []))} colors={len(parsed.get('colors', []))} "
        f"highlights={len(parsed.get('highlights', []))} font_sizes={len(parsed.get('font_sizes', []))}"
    )
    print(f"  preview={_preview(text)!r}")
    for run in parsed.get("runs", ()):
        print(f"  run {_fmt_range(run):>9} {run['style']}")
    for color in parsed.get("colors", ()):
        print(f"  color {_fmt_range(color):>7} #{color['color'][0]:02x}{color['color'][1]:02x}{color['color'][2]:02x}")
    for highlight in parsed.get("highlights", ()):
        print(
            f"  highlight {_fmt_range(highlight):>3} "
            f"#{highlight['color'][0]:02x}{highlight['color'][1]:02x}{highlight['color'][2]:02x}"
        )
    for font in parsed.get("font_sizes", ()):
        print(f"  font {_fmt_range(font):>8} {font['font_size']:.2f}")

    lines = text.split("\n")
    for idx, paragraph in enumerate(paragraphs):
        if not show_all_paragraphs and _paragraph_is_default(paragraph):
            continue
        line = lines[idx] if idx < len(lines) else ""
        print(
            f"  paragraph {idx:>3} align={paragraph.get('alignment', 'left'):<6} "
            f"indent={paragraph.get('indent', 0)} style={paragraph.get('style') or '-':<8} "
            f"spacing={paragraph.get('line_spacing') or '-'} list={paragraph.get('list') or '-'} "
            f"text={_preview(line)!r}"
        )


def _print_note_metadata(note_meta: dict | None) -> None:
    if note_meta is None:
        print("note_metadata: none")
        return
    print(
        f"note_metadata fmt={note_meta.get('format_version')} size={note_meta.get('width')}x{note_meta.get('height')} "
        f"title={note_meta.get('title')!r} created={note_meta.get('created_time')} "
        f"modified={note_meta.get('modified_time')} title_size={note_meta.get('title_size')}"
    )
    for clip in note_meta.get("voice_clips", ()):
        print(
            f"  voice_clip label={clip['label']!r} duration={clip['duration']!r} "
            f"label_off=0x{clip['label_off']:x} duration_off=0x{clip['duration_off']:x}"
        )
    for record in note_meta.get("tail_records", ()):
        kind = record["kind"]
        if kind == "tail_sentinel":
            print(f"  tail_record sentinel off=0x{record['off']:x}")
        elif kind == "voice_clip":
            print(
                f"  tail_record voice_clip off=0x{record['off']:x} "
                f"label={record['label']!r} duration={record['duration']!r} "
                f"post_u32={record['post_u32']} post_u64_pairs={record.get('post_u64_pairs', [])}"
            )
        elif kind == "pen_preload_path":
            print(
                f"  tail_record pen_preload off=0x{record['off']:x} "
                f"path={record['path']!r} param_hint={record.get('param_hint')!r}"
            )
        elif kind == "tail_hash_block":
            relation = record.get("page_id_info_relation") or {}
            print(
                f"  tail_record hash_block off=0x{record['off']:x} "
                f"prefix={record['prefix_u32']} hash32={record['hash32'][:16]}... "
                f"pageIdInfo={relation}"
            )
        elif kind == "pen_preload_prelude":
            print(
                f"  tail_record preload_prelude off=0x{record['off']:x} "
                f"param={record.get('param')!r} prefix={record.get('prefix_u32', [])} "
                f"trailing={record.get('trailing_u32', [])}"
            )
        elif kind == "pen_preload_prelude_raw":
            print(
                f"  tail_record preload_prelude_raw off=0x{record['off']:x} "
                f"raw_u32={record.get('raw_u32', [])}"
            )
        elif kind == "pen_style_tail":
            print(
                f"  tail_record pen_style_tail off=0x{record['off']:x} "
                f"width={record.get('width', 0.0):.3f} argb={record.get('argb')} "
                f"param={record.get('param')!r} raw_u32={record.get('raw_u32', [])}"
            )
        elif kind == "voice_clip_header":
            print(f"  tail_record voice_clip_header off=0x{record['off']:x} raw_u32={record.get('raw_u32', [])}")
        elif kind == "voice_clip_post":
            print(
                f"  tail_record voice_clip_post off=0x{record['off']:x} "
                f"raw_u32={record.get('raw_u32', [])} raw_u64_pairs={record.get('raw_u64_pairs', [])}"
            )
        elif kind == "tail_post_hash_u32":
            print(f"  tail_record tail_post_hash_u32 off=0x{record['off']:x} value=0x{record['value']:08x}")


def _print_text_box_debug(page_idx: int, result: dict, layout_debug: list[dict] | None = None) -> None:
    if not result["text_boxes"]:
        return
    print(f"page {page_idx} {result['uuid'][:8]} text_boxes={len(result['text_boxes'])}")
    for idx, box in enumerate(result["text_boxes"]):
        bbox = _fmt_optional_bbox(box["bbox"])
        print(
            f"  object={box['object_idx']} angle={box.get('angle_deg') or 0.0:.2f} "
            f"bbox={bbox} chars={len(box['text'])} font={box.get('font_size') or '-'} "
            f"text_off=0x{box['text_off']:x} object_off=0x{box['object_off']:x} "
            f"text={_preview(box['text'])!r}"
        )
        for run in box.get("runs", ()):
            print(f"    run {_fmt_range(run):>9} {run['style']}")
        for color in box.get("colors", ()):
            print(f"    color {_fmt_range(color):>7} #{color['color'][0]:02x}{color['color'][1]:02x}{color['color'][2]:02x}")
        for font in box.get("font_sizes", ()):
            print(f"    font {_fmt_range(font):>8} {font['font_size']:.2f}")
        if box.get("frame_midpoints"):
            pts = ", ".join(f"({x:.1f},{y:.1f})" for x, y in box["frame_midpoints"])
            print(f"    frame_midpoints {pts}")
        if layout_debug:
            debug = layout_debug[idx]
            print(
                f"    layout bbox_inner={debug['bbox_inner_w']:.1f}x{debug['bbox_inner_h']:.1f} "
                f"anchor=({debug['anchor_x']:.1f},{debug['anchor_y']:.1f}) "
                f"wrap={debug['wrap_width']:.1f} line_h={debug['line_h']:.1f} blank_h={debug['blank_h']:.1f}"
            )
            for note in debug.get("heuristics", ()):
                print(f"      heuristic: {note}")
            for line_idx, line in enumerate(debug["lines"], 1):
                print(f"      line {line_idx:>2} y={line['y']:.1f} text={_preview(line['text'])!r}")
                for seg in line["segments"]:
                    print(
                        f"        seg x={seg['x']:.1f} {_style_flags(seg['style'])} "
                        f"text={_preview(seg['text'], limit=48)!r}"
                    )


def _text_debug_json(
    note_metadata: dict | None,
    typed_text: dict | None,
    page_results: list[tuple[int, str, dict]],
    layout_debug_by_page: dict[int, list[dict]] | None = None,
) -> dict:
    pages = []
    for page_idx, page_name, result in page_results:
        pages.append({
            "page": page_idx,
            "name": page_name,
            "uuid": result["uuid"],
            "text_boxes": result["text_boxes"],
            "text_box_layout_debug": (layout_debug_by_page or {}).get(page_idx),
        })
    return {"note_metadata": note_metadata, "typed_text": typed_text, "pages": pages}


def cmd_text(args: argparse.Namespace) -> None:
    """Print note.note typed text metadata and page-object text-box metadata."""
    note = load_note(args.file) or b""
    note_metadata = parse_note_metadata(note)
    note_metadata = annotate_note_tail_with_page_id_info(note_metadata, load_page_id_info(args.file))
    typed_text = parse_typed_text(note)
    page_names = list_pages(args.file)
    if args.page:
        page_names = [p for p in page_names if args.page in p]
        if not page_names:
            print(f"no .page file matches {args.page!r}", file=sys.stderr)
            sys.exit(1)
    page_results = []
    for page_idx, page_name in enumerate(list_pages(args.file), 1):
        if page_name not in page_names:
            continue
        _, page_data = load_page(args.file, page_name)
        page_results.append((page_idx, page_name, parse_page(page_data)))
    layout_debug_by_page = None
    if args.layout_debug:
        from pysdocx.render import debug_text_box_layout

        layout_debug_by_page = {}
        for page_idx, _page_name, result in page_results:
            layout_debug_by_page[page_idx] = [
                debug_text_box_layout(box, page_size=(result["width"], result["height"]))
                for box in result["text_boxes"]
            ]

    if args.json:
        print(
            json.dumps(
                _text_debug_json(note_metadata, typed_text, page_results, layout_debug_by_page),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    _print_note_metadata(note_metadata)
    if typed_text is None:
        print("typed_text: none")
    else:
        _print_typed_text_debug(typed_text, args.all_paragraphs)
    for page_idx, _page_name, result in page_results:
        _print_text_box_debug(page_idx, result, (layout_debug_by_page or {}).get(page_idx))


def cmd_render(args: argparse.Namespace) -> None:
    # Imported lazily so `dump`/`stroke-table` don't pull in matplotlib/Pillow.
    from pysdocx.render import render_document

    out_dir = args.outdir or Path("outputs_render") / args.file.stem
    render_document(
        args.file,
        out=out_dir,
        fmt=args.format,
        bg=args.bg,
        page=args.page,
        table_page=args.table_page,
        show=False,
    )
    stem = args.file.stem
    pages = [args.page] if args.page else "all"
    print(f"wrote {stem}-page-NN.{args.format} to {out_dir} (pages: {pages})")


def cmd_media_info(args: argparse.Namespace) -> None:
    media = list_media_info(args.file, verify_hash=args.verify_hash)
    if media is None:
        print("mediaInfo: none")
        return
    print(
        f"mediaInfo magic=0x{media['magic']:x} count={media['count']} "
        f"eof={media['eof']!r} valid_eof={media['valid_eof']}"
    )
    for record in media["records"]:
        sha = record["sha256"]
        sha_part = sha if args.full_hash else sha[:16] + "..."
        hash_part = ""
        if args.verify_hash:
            hash_part = f" sha256_matches={record.get('sha256_matches')}"
        print(
            f"  [{record['media_index']:>2}] off=0x{record['off']:x} size={record['payload_size']:<3} "
            f"exists={record['exists']} index_name={record['index_matches_name']} "
            f"zip_size={record.get('zip_size')} tail_tag={record.get('tail_tag')} "
            f"time_candidate={record.get('time_candidate')} marker={record.get('tail_marker')} "
            f"sha256={sha_part}{hash_part} name={record['name']!r}"
        )
        if args.raw_tail:
            print(f"       raw_tail={record['raw_tail']}")
    if media.get("unlisted_media"):
        print("unlisted media:")
        for name in media["unlisted_media"]:
            print(f"  {name}")


def cmd_inventory(args: argparse.Namespace) -> None:
    targets = args.paths or [Path("samples")]
    report = build_inventory(targets)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"inventory sample_count={report['sample_count']}")
    print("object header profiles:")
    for row in report["object_header_profiles"]:
        print(
            f"  type={row['object_type']:<14} family={row['family']:<16} "
            f"sig={row['signature']:<12} count={row['count']}"
        )
    print("note profiles:")
    for row in report["note_profiles"]:
        print(
            f"  family={row['family']:<18} sig={row['signature']:<28} count={row['count']}"
        )
    print("note tail kinds:")
    for kind, count in sorted(report["note_tail_profiles"]["kinds"].items()):
        print(f"  {kind:<20} count={count}")
    if report["note_tail_profiles"].get("page_id_info_relations"):
        print("note tail -> pageIdInfo:")
        for kind, count in sorted(report["note_tail_profiles"]["page_id_info_relations"].items()):
            print(f"  {kind:<28} count={count}")
    if report["note_tail_profiles"].get("tail_hash_prefixes"):
        print("note tail hash prefixes:")
        for row in report["note_tail_profiles"]["tail_hash_prefixes"]:
            print(f"  {row['prefix_u32']} count={row['count']}")
    if report["note_tail_profiles"].get("preload_paths"):
        print("note preload paths:")
        for path, count in sorted(report["note_tail_profiles"]["preload_paths"].items()):
            print(f"  {path:<58} count={count}")
    if report["note_tail_profiles"].get("preload_param_hints"):
        print("note preload param hints:")
        for hint, count in sorted(report["note_tail_profiles"]["preload_param_hints"].items()):
            print(f"  {hint!r:<16} count={count}")
    if report["note_tail_profiles"].get("preload_prelude_params"):
        print("note preload prelude params:")
        for hint, count in sorted(report["note_tail_profiles"]["preload_prelude_params"].items()):
            print(f"  {hint!r:<16} count={count}")
    if report["note_tail_profiles"].get("preload_prelude_shapes"):
        print("note preload prelude raw shapes:")
        for row in report["note_tail_profiles"]["preload_prelude_shapes"][:12]:
            print(f"  prefix={row['prefix_u32']} trailing={row['trailing_u32']} count={row['count']}")
    if report["note_tail_profiles"].get("preload_prelude_raw_shapes"):
        print("note preload prelude undecoded raw shapes:")
        for row in report["note_tail_profiles"]["preload_prelude_raw_shapes"][:12]:
            print(f"  raw_u32={row['raw_u32']} count={row['count']}")
    if report["note_tail_profiles"].get("pen_style_tail_params"):
        print("note pen style tail params:")
        for hint, count in sorted(report["note_tail_profiles"]["pen_style_tail_params"].items()):
            print(f"  {hint!r:<16} count={count}")
    if report["note_tail_profiles"].get("pen_style_tail_shapes"):
        print("note pen style tail raw shapes:")
        for row in report["note_tail_profiles"]["pen_style_tail_shapes"]:
            print(
                f"  width={row['width']:<6} argb={row['argb']} param={row['param']!r} "
                f"raw_u32={row['raw_u32']} count={row['count']}"
            )
    if report["note_tail_profiles"].get("voice_post_u32"):
        print("note voice post_u32:")
        for row in report["note_tail_profiles"]["voice_post_u32"]:
            print(f"  {row['post_u32']} count={row['count']}")
    if report["note_tail_profiles"].get("voice_post_u64_pairs"):
        print("note voice post_u64 pairs:")
        for row in report["note_tail_profiles"]["voice_post_u64_pairs"]:
            print(f"  {row['post_u64_pairs']} count={row['count']}")
    if report["note_tail_profiles"].get("voice_post_record_u64_pairs"):
        print("note voice post-record u64 pairs:")
        for row in report["note_tail_profiles"]["voice_post_record_u64_pairs"]:
            print(f"  {row['raw_u64_pairs']} count={row['count']}")
    tail_cov = report["note_tail_profiles"].get("coverage") or {}
    tail_known = tail_cov.get("known_bytes", 0)
    tail_unknown = tail_cov.get("unknown_bytes", 0)
    tail_total = tail_known + tail_unknown
    tail_ratio = tail_known / tail_total if tail_total else 1.0
    print(
        f"note tail coverage: known={tail_known} unknown={tail_unknown} "
        f"known_ratio={tail_ratio:.2%}"
    )
    for row in tail_cov.get("per_file", ()):
        print(
            f"  {row['file']:<58} tail={row['tail_len']:<5} known={row['known_bytes']:<4} "
            f"unknown={row['unknown_bytes']:<4} gaps={row['gap_count']} max_gap={row['max_gap']}"
        )
    if tail_cov.get("gap_prefixes"):
        print("note tail unknown-gap prefixes:")
        for row in tail_cov["gap_prefixes"]:
            print(f"  {row['prefix_hex']:<32} count={row['count']}")
    ext = report.get("object_header_ext") or {}
    print(
        f"object header ext: count={ext.get('count', 0)} "
        f"dim_mismatches={len(ext.get('dimension_mismatches', []))} "
        f"extra_key_blocks={ext.get('extra_key_blocks', 0)} "
        f"extra_key_bad={len(ext.get('extra_key_bad', []))}"
    )
    for row in ext.get("per_file", ()):
        print(
            f"  {row['file']:<58} n={row['count']:<4} "
            f"seq={row['seq_min']}..{row['seq_max']} uniq={row['seq_unique']} "
            f"inv={row['seq_inversions']} counters={row['counter_unique']} "
            f"repeated_groups={row['repeated_counter_groups']} offsets={row['ext_offsets']}"
        )
    print("attachment bag keys:")
    for key, count in sorted(report["attachment_profiles"]["keys"].items()):
        print(f"  {key:<20} count={count}")
    media = report.get("media_info_profiles") or {}
    print(
        f"mediaInfo: records={media.get('records', 0)} parsed_files={media.get('parsed_files', 0)} "
        f"sha_mismatches={media.get('sha_mismatches', 0)} missing_media={media.get('missing_media', 0)} "
        f"unlisted_media={media.get('unlisted_media', 0)} bad_eof={media.get('bad_eof', 0)}"
    )
    if media.get("magic"):
        print("mediaInfo magic:")
        for key, count in sorted(media["magic"].items()):
            print(f"  {key:<8} count={count}")
    if media.get("tail_tags"):
        print("mediaInfo tail tags:")
        for key, count in sorted(media["tail_tags"].items()):
            print(f"  {key:<8} count={count}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m pysdocx")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="list a .sdocx archive's contents")
    p_dump.add_argument("file", type=Path)
    p_dump.set_defaults(func=cmd_dump)

    p_table = sub.add_parser("stroke-table", help="per-page stroke parse diagnostics")
    p_table.add_argument("file", type=Path)
    p_table.add_argument("--page", help="filter to .page files whose name contains this substring")
    p_table.add_argument("--detail", action="store_true", help="print one row per attempted stroke")
    p_table.set_defaults(func=cmd_stroke_table)

    p_objects = sub.add_parser("objects", help="print the parsed page layer/object tree")
    p_objects.add_argument("file", type=Path)
    p_objects.add_argument("--page", help="filter to .page files whose name contains this substring")
    p_objects.add_argument("--detail", action="store_true", help="print object header details")
    p_objects.add_argument("--summary", action="store_true", help="print aggregate object type counts")
    p_objects.set_defaults(func=cmd_objects)

    p_text = sub.add_parser("text", help="print typed-text and text-box rich-text diagnostics")
    p_text.add_argument("file", type=Path)
    p_text.add_argument("--page", help="filter text boxes to .page files whose name contains this substring")
    p_text.add_argument(
        "--all-paragraphs",
        action="store_true",
        help="include default paragraphs, not only paragraphs with decoded metadata",
    )
    p_text.add_argument(
        "--layout-debug",
        action="store_true",
        help="also run the current renderer heuristics and print the wrapped text-box lines they produce",
    )
    p_text.add_argument("--json", action="store_true", help="emit parsed text/page metadata as JSON")
    p_text.set_defaults(func=cmd_text)

    p_render = sub.add_parser("render", help="render each page to an image (one file per page)")
    p_render.add_argument("file", type=Path)
    p_render.add_argument(
        "outdir", type=Path, nargs="?", help="output directory (default: outputs_render/<file stem>/)"
    )
    p_render.add_argument("--format", default="png", choices=("png", "svg"), help="output image format")
    p_render.add_argument("--page", type=int, help="render only this 1-based page index")
    p_render.add_argument("--table-page", type=int, help="force note-level table rendering onto this page")
    p_render.add_argument("--bg", choices=("dark", "white"), help="page background (default: the file's stored color)")
    p_render.set_defaults(func=cmd_render)

    p_media = sub.add_parser("media-info", help="print media/mediaInfo.dat manifest diagnostics")
    p_media.add_argument("file", type=Path)
    p_media.add_argument("--verify-hash", action="store_true", help="hash media files and compare SHA-256")
    p_media.add_argument("--full-hash", action="store_true", help="print full SHA-256 values")
    p_media.add_argument("--raw-tail", action="store_true", help="print the raw tail bytes for each manifest record")
    p_media.set_defaults(func=cmd_media_info)

    p_inventory = sub.add_parser("inventory", help="summarize corpus-level format coverage/profiles")
    p_inventory.add_argument("paths", type=Path, nargs="*", help="files or directories to scan (default: samples/)")
    p_inventory.add_argument("--json", action="store_true", help="emit machine-readable inventory JSON")
    p_inventory.set_defaults(func=cmd_inventory)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
