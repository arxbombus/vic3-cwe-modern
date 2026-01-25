"""AST query helpers."""

from clausewitz.query.query_utils import (
    AstEntryRef,
    Path,
    endswith_path_pattern,
    find_blocks_by_path,
    find_entries,
    find_entries_by_path,
    find_lists_by_path,
    match_path_pattern,
    match_segment,
    parse_path,
    replace_values,
    scale_numeric_values,
    walk_entries,
)

__all__ = [
    "AstEntryRef",
    "Path",
    "endswith_path_pattern",
    "find_blocks_by_path",
    "find_entries",
    "find_entries_by_path",
    "find_lists_by_path",
    "match_path_pattern",
    "match_segment",
    "parse_path",
    "replace_values",
    "scale_numeric_values",
    "walk_entries",
]
