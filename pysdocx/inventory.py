"""Corpus-level inventory of decoded vs partially-decoded `.sdocx` structures."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from pysdocx.container import list_pages, load_note, load_page, load_page_id_info
from pysdocx.note import annotate_note_tail_with_page_id_info, parse_note_metadata, parse_tables, parse_typed_text
from pysdocx.page import parse_page


COVERAGE_MATRIX = [
    {
        "surface": "zip_container.pageIdInfo.dat",
        "status": ["Structural", "Semantic"],
        "decoded": ["true_page_order"],
        "unknown": [],
    },
    {
        "surface": "zip_container.note.note",
        "status": ["Structural", "Semantic"],
        "decoded": [
            "top_level_metadata",
            "typed_text",
            "tables",
            "title",
            "voice_clip_labels_durations",
            "tail_record_boundaries",
            "pen_preload_paths",
            "tail_hash_page_id_info_relation",
        ],
        "unknown": ["full_note_note_schema", "raw_tail_record_field_semantics", "remaining_metadata_flags"],
    },
    {
        "surface": "page.layer_object_tree",
        "status": ["Structural"],
        "decoded": ["layer_count", "current_layer_index", "object_boundaries", "child_recursion"],
        "unknown": ["layer_flags_semantics", "all_content_flags_semantics"],
    },
    {
        "surface": "page.common_object_header",
        "status": ["Structural", "Semantic"],
        "decoded": [
            "header_fields",
            "bbox",
            "uuid",
            "modified_time",
            "field_flags_size_model",
            "field_flag_bit_0x1_rotation",
            "field_flag_bit_0x20_extra_key_stroke_shape",
            "field_flag_bit_0x40000_header_ext",
            "field_flag_bit_0x8000_media_shape_family",
        ],
        "unknown": ["object_flags_semantics", "header_ext_seq_counter_semantics"],
    },
    {
        "surface": "page.strokes",
        "status": ["Structural", "Semantic"],
        "decoded": ["payload_layouts", "coordinates", "pressure", "width", "color", "tool_family"],
        "unknown": [],
    },
    {
        "surface": "page.shapes",
        "status": ["Structural", "Semantic", "Marker / Inferred"],
        "decoded": ["shape_membership", "outline_geometry", "type_classification", "colors", "width"],
        "unknown": ["full_payload_schema_per_shape_variant"],
    },
    {
        "surface": "page.images",
        "status": ["Structural", "Semantic", "Marker / Inferred"],
        "decoded": ["image_membership", "bbox", "media_index", "rotation"],
        "unknown": ["full_media_link_schema"],
    },
    {
        "surface": "page.drawings",
        "status": ["Structural", "Marker / Inferred"],
        "decoded": ["drawing_membership", "raster_media_link", "placement_bbox"],
        "unknown": ["formal_object_level_schema"],
    },
    {
        "surface": "page.text_boxes",
        "status": ["Structural", "Semantic"],
        "decoded": ["membership", "text", "style_runs", "rotation", "frame_midpoints"],
        "unknown": ["inner_text_frame_fields", "full_layout_semantics"],
    },
    {
        "surface": "page.attachments",
        "status": ["Structural", "Semantic", "Marker / Inferred"],
        "decoded": ["archive_attachment_listing", "sticky_note_property_bags", "sticky_bbox", "attachment_kind"],
        "unknown": ["audio_page_placement_structure", "general_attachment_page_model"],
    },
    {
        "surface": "rendering",
        "status": ["Heuristic"],
        "decoded": ["typed_text_target_page", "some_rotated_text_box_layout_behaviour"],
        "unknown": ["samsung_true_pagination_rules", "true_rotated_inner_text_layout"],
    },
]


def _iter_paths(targets: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for target in targets:
        if target.is_dir():
            paths.extend(sorted(target.glob("*.sdocx")))
        elif target.suffix == ".sdocx":
            paths.append(target)
    seen = set()
    unique = []
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _iter_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        yield from _iter_objects(obj["children"])


def _note_profile(meta: dict | None, typed_text: dict | None, tables: list[dict]) -> dict | None:
    if meta is None:
        return None
    has_typed_text = bool(typed_text and typed_text.get("text"))
    flags = meta.get("flags", 0) or 0
    meta_flags = meta.get("meta_flags", 0) or 0
    known_bits = []
    unknown_flag_bits = []
    # `meta_flags` bit 0x2000 is set on exactly the two table-bearing notes in the corpus and on no
    # other note (including typed-but-tableless ones), so it decodes as a "has tables" flag; it agrees
    # with the independently-parsed table cells here. 0x80/0x200/0x800/0x40000/0x80000 are set on every
    # note (constant base bits). 0x400/0x8000 vary but do not line up with any observable feature yet.
    META_TABLES_FLAG = 0x2000
    META_BASE_BITS = 0x80 | 0x200 | 0x800 | 0x40000 | 0x80000
    if meta_flags & META_TABLES_FLAG:
        known_bits.append("meta_tables_flag_0x2000")
    if meta_flags & META_BASE_BITS:
        known_bits.append("meta_base_bits")
    for bit in (0x400, 0x8000):
        if meta_flags & bit:
            unknown_flag_bits.append(f"meta:0x{bit:x}")
    if flags & 0x8:
        unknown_flag_bits.append("0x8")
    if meta.get("voice_clips"):
        known_bits.append("voice_clip_block_present")
    if any(record.get("kind") == "pen_preload_path" for record in meta.get("tail_records", ())):
        known_bits.append("pen_preload_tail_present")
    if any(record.get("kind") == "tail_hash_block" for record in meta.get("tail_records", ())):
        known_bits.append("tail_hash_block_present")
    if has_typed_text:
        known_bits.append("typed_text_present")
    if tables:
        known_bits.append("table_cells_present")

    family = f"v{meta.get('format_version')}"
    if has_typed_text:
        family += "_typed"
    if tables:
        family += "_tables"
    if meta.get("voice_clips"):
        family += "_voice"
    if any(record.get("kind") == "pen_preload_path" for record in meta.get("tail_records", ())):
        family += "_preload"
    if any(record.get("kind") == "tail_hash_block" for record in meta.get("tail_records", ())):
        family += "_hash"

    return {
        "signature": f"fmt{meta.get('format_version')}/flags0x{flags:x}/meta0x{meta_flags:x}",
        "family": family,
        "known_features": known_bits,
        "unknown_bits": unknown_flag_bits,
    }


def _merge_spans(spans: list[tuple[int, int]], lower: int, upper: int) -> list[tuple[int, int]]:
    """Clamp and merge byte ranges so overlapping marker hits do not over-count coverage."""
    clipped = sorted((max(lower, a), min(upper, b)) for a, b in spans if b > lower and a < upper)
    merged: list[tuple[int, int]] = []
    for start, end in clipped:
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _note_tail_coverage(note_bytes: bytes, meta: dict | None) -> dict | None:
    if meta is None:
        return None
    tail_start = meta.get("offset_to_data")
    if not isinstance(tail_start, int) or not (0 <= tail_start <= len(note_bytes)):
        return None

    tail_end = len(note_bytes)
    records = meta.get("tail_records", ())
    spans = _merge_spans(
        [(record["off"], record["end"]) for record in records if "off" in record and "end" in record],
        tail_start,
        tail_end,
    )
    known_bytes = sum(end - start for start, end in spans)
    cursor = tail_start
    gaps = []
    for start, end in spans:
        if cursor < start:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < tail_end:
        gaps.append((cursor, tail_end))

    return {
        "tail_start": tail_start,
        "tail_len": tail_end - tail_start,
        "known_bytes": known_bytes,
        "unknown_bytes": sum(end - start for start, end in gaps),
        "known_ratio": (known_bytes / (tail_end - tail_start)) if tail_end > tail_start else 1.0,
        "gap_count": len(gaps),
        "max_gap": max((end - start for start, end in gaps), default=0),
        "gap_prefixes": [
            {
                "off": start,
                "size": end - start,
                "prefix_hex": note_bytes[start : min(end, start + 16)].hex(),
            }
            for start, end in gaps[:8]
        ],
    }


def build_inventory(targets: list[Path]) -> dict:
    paths = _iter_paths(targets)
    object_profiles = Counter()
    object_profiles_by_type: dict[str, Counter] = defaultdict(Counter)
    object_examples: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    note_profiles = Counter()
    note_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    attachment_keys = Counter()
    attachment_kind_counts = Counter()
    attachment_examples: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    note_tail_kind_counts = Counter()
    note_tail_examples: dict[str, list[str]] = defaultdict(list)
    note_tail_relations = Counter()
    note_tail_hash_prefixes = Counter()
    note_preload_paths = Counter()
    note_preload_param_hints = Counter()
    note_voice_post_u32 = Counter()
    note_tail_gap_prefixes = Counter()
    note_tail_coverage_rows = []
    header_ext_total = 0
    header_ext_dim_mismatches = []
    header_ext_file_summaries = []
    extra_key_total = 0
    extra_key_bad = []
    sample_rows = []

    for path in paths:
        note = load_note(path)
        note_meta = parse_note_metadata(note) if note else None
        page_id_info = load_page_id_info(path)
        note_meta = annotate_note_tail_with_page_id_info(note_meta, page_id_info)
        typed_text = parse_typed_text(note) if note else None
        tables = parse_tables(note) if note else []
        has_typed_text = bool(typed_text and typed_text.get("text"))
        note_profile = _note_profile(note_meta, typed_text, tables)
        if note_profile is not None:
            nkey = (note_profile["family"], note_profile["signature"])
            note_profiles[nkey] += 1
            if len(note_examples[nkey]) < 5:
                note_examples[nkey].append(path.name)
        tail_coverage = _note_tail_coverage(note, note_meta) if note else None
        if tail_coverage is not None:
            for gap in tail_coverage["gap_prefixes"]:
                note_tail_gap_prefixes[gap["prefix_hex"]] += 1
            note_tail_coverage_rows.append({
                "file": path.name,
                "tail_start": tail_coverage["tail_start"],
                "tail_len": tail_coverage["tail_len"],
                "known_bytes": tail_coverage["known_bytes"],
                "unknown_bytes": tail_coverage["unknown_bytes"],
                "known_ratio": tail_coverage["known_ratio"],
                "gap_count": tail_coverage["gap_count"],
                "max_gap": tail_coverage["max_gap"],
                "gap_prefixes": tail_coverage["gap_prefixes"],
            })
        for record in (note_meta or {}).get("tail_records", ()):
            note_tail_kind_counts[record["kind"]] += 1
            if len(note_tail_examples[record["kind"]]) < 5:
                note_tail_examples[record["kind"]].append(path.name)
            relation = record.get("page_id_info_relation")
            if relation:
                if relation.get("matches_page_id_head_exact"):
                    note_tail_relations["page_id_head_exact"] += 1
                if relation.get("matches_page_id_head_shifted_with_u32_2"):
                    note_tail_relations["page_id_head_shifted_u32_2"] += 1
            if record["kind"] == "tail_hash_block":
                note_tail_hash_prefixes[tuple(record.get("prefix_u32", ()))] += 1
            elif record["kind"] == "pen_preload_path":
                note_preload_paths[record.get("path", "")] += 1
                if record.get("param_hint"):
                    note_preload_param_hints[record["param_hint"]] += 1
            elif record["kind"] == "voice_clip":
                note_voice_post_u32[tuple(record.get("post_u32", ()))] += 1

        page_count = 0
        object_count = 0
        sticky_count = 0
        attachment_count = 0
        object_order = 0
        file_ext_rows = []
        for page_name in list_pages(path):
            page_count += 1
            _, data = load_page(path, page_name)
            result = parse_page(data)
            object_count += result["object_count"]
            sticky_count += len(result.get("sticky_notes", ()))
            attachment_count += len(result.get("attachment_placements", ()))
            for placement in result.get("attachment_placements", ()):
                keys = tuple(placement.get("keys", ()))
                attachment_kind_counts[placement["kind"]] += 1
                attachment_keys.update(keys)
                pkey = (placement["kind"], keys)
                if len(attachment_examples[pkey]) < 5:
                    attachment_examples[pkey].append(f"{path.name}:{result['uuid'][:8]}")
            for layer in result["layers"]:
                for obj in _iter_objects(layer["objects"]):
                    object_order += 1
                    profile = obj.get("header_profile")
                    if not profile:
                        continue
                    header = obj.get("header") or {}
                    ext = header.get("ext_block")
                    if ext:
                        header_ext_total += 1
                        row = {
                            "file": path.name,
                            "page_uuid": result["uuid"][:8],
                            "object_order": object_order,
                            "object_type": obj["type"],
                            "counter": ext["counter"],
                            "seq": ext["seq"],
                            "off": ext["off"],
                        }
                        file_ext_rows.append(row)
                        if (ext["page_width"], ext["page_height"]) != (result["width"], result["height"]):
                            header_ext_dim_mismatches.append({
                                **row,
                                "decoded_page": [ext["page_width"], ext["page_height"]],
                                "actual_page": [result["width"], result["height"]],
                            })
                    extra_key = header.get("extra_key_block")
                    if extra_key:
                        extra_key_total += 1
                        if not (
                            extra_key["head_ok"]
                            and extra_key["key_len"] == 23
                            and extra_key["key"] == "extra_key_stroke_shape"
                            and extra_key["trailing"] == 1
                        ):
                            extra_key_bad.append({
                                "file": path.name,
                                "page_uuid": result["uuid"][:8],
                                "object_order": object_order,
                                "object_type": obj["type"],
                                "block": extra_key,
                            })
                    okey = (obj["type"], profile["family"], profile["signature"])
                    object_profiles[okey] += 1
                    object_profiles_by_type[obj["type"]][(profile["family"], profile["signature"])] += 1
                    if len(object_examples[okey]) < 5:
                        object_examples[okey].append(path.name)

        if file_ext_rows:
            seqs = [row["seq"] for row in file_ext_rows]
            counters = Counter(row["counter"] for row in file_ext_rows)
            repeated_sizes = Counter(count for count in counters.values() if count > 1)
            seq_inversions = sum(
                1
                for prev, cur in zip(file_ext_rows, file_ext_rows[1:])
                if cur["seq"] < prev["seq"]
            )
            header_ext_file_summaries.append({
                "file": path.name,
                "count": len(file_ext_rows),
                "seq_unique": len(set(seqs)),
                "seq_min": min(seqs),
                "seq_max": max(seqs),
                "seq_inversions": seq_inversions,
                "counter_unique": len(counters),
                "repeated_counter_groups": sum(1 for count in counters.values() if count > 1),
                "repeated_counter_size_counts": dict(sorted(repeated_sizes.items())),
                "ext_offsets": sorted({row["off"] for row in file_ext_rows}),
            })

        sample_rows.append({
            "file": path.name,
            "pages": page_count,
            "objects": object_count,
            "typed_text": has_typed_text,
            "typed_text_chars": len(typed_text.get("text", "")) if typed_text else 0,
            "tables": len(tables),
            "voice_clips": len((note_meta or {}).get("voice_clips", ())),
            "sticky_placements": sticky_count,
            "attachment_placements": attachment_count,
            "header_ext_blocks": len(file_ext_rows),
            "note_profile": note_profile,
            "note_tail_kinds": sorted({record["kind"] for record in (note_meta or {}).get("tail_records", ())}),
        })

    return {
        "sample_count": len(paths),
        "samples": sample_rows,
        "coverage_matrix": COVERAGE_MATRIX,
        "object_header_profiles": [
            {
                "object_type": obj_type,
                "family": family,
                "signature": signature,
                "count": count,
                "example_files": object_examples[(obj_type, family, signature)],
            }
            for (obj_type, family, signature), count in sorted(object_profiles.items())
        ],
        "object_header_profiles_by_type": {
            obj_type: [
                {"family": family, "signature": signature, "count": count}
                for (family, signature), count in sorted(counter.items())
            ]
            for obj_type, counter in sorted(object_profiles_by_type.items())
        },
        "note_profiles": [
            {
                "family": family,
                "signature": signature,
                "count": count,
                "example_files": note_examples[(family, signature)],
            }
            for (family, signature), count in sorted(note_profiles.items())
        ],
        "note_tail_profiles": {
            "kinds": dict(sorted(note_tail_kind_counts.items())),
            "examples": {kind: examples for kind, examples in sorted(note_tail_examples.items())},
            "page_id_info_relations": dict(sorted(note_tail_relations.items())),
            "tail_hash_prefixes": [
                {"prefix_u32": list(prefix), "count": count}
                for prefix, count in sorted(note_tail_hash_prefixes.items())
            ],
            "preload_paths": dict(sorted(note_preload_paths.items())),
            "preload_param_hints": dict(sorted(note_preload_param_hints.items())),
            "voice_post_u32": [
                {"post_u32": list(post_u32), "count": count}
                for post_u32, count in sorted(note_voice_post_u32.items())
            ],
            "coverage": {
                "known_bytes": sum(row["known_bytes"] for row in note_tail_coverage_rows),
                "unknown_bytes": sum(row["unknown_bytes"] for row in note_tail_coverage_rows),
                "gap_prefixes": [
                    {"prefix_hex": prefix, "count": count}
                    for prefix, count in note_tail_gap_prefixes.most_common(12)
                ],
                "per_file": note_tail_coverage_rows,
            },
        },
        "object_header_ext": {
            "count": header_ext_total,
            "dimension_mismatches": header_ext_dim_mismatches[:10],
            "extra_key_blocks": extra_key_total,
            "extra_key_bad": extra_key_bad[:10],
            "per_file": header_ext_file_summaries,
        },
        "attachment_profiles": {
            "kinds": dict(sorted(attachment_kind_counts.items())),
            "keys": dict(sorted(attachment_keys.items())),
            "bags": [
                {
                    "kind": kind,
                    "keys": list(keys),
                    "count": len(examples),
                    "example_pages": examples,
                }
                for (kind, keys), examples in sorted(attachment_examples.items())
            ],
        },
    }
