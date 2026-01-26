from __future__ import annotations

from typing import Iterable

from clausewitz import ClausewitzDocument
from clausewitz.model import Block, Operator, ScalarValue, TaggedValue
from clausewitz.query import find_entries


def replace_values(
    document: ClausewitzDocument,
    *,
    key_pattern: str,
    new_raw: str,
    ancestor_suffix_pattern: str,
    exclude_key_patterns: Iterable[str],
    operator: Operator | None,
) -> int:
    count = _count_entries(
        document,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
        operator=operator,
        numeric=False,
        require_block=False,
    )
    if count > 0:
        document.replace_values(
            key_pattern=key_pattern,
            new_raw=new_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=tuple(exclude_key_patterns),
            operator=operator,
        )
    return count


def scale_numeric_values(
    document: ClausewitzDocument,
    *,
    key_pattern: str,
    factor: float,
    ancestor_suffix_pattern: str,
    exclude_key_patterns: Iterable[str],
    operator: Operator,
) -> int:
    count = _count_entries(
        document,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
        operator=operator,
        numeric=True,
        require_block=False,
    )
    if count > 0:
        document.scale_numeric_values(
            key_pattern=key_pattern,
            factor=factor,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=tuple(exclude_key_patterns),
            operator=operator,
        )
    return count


def delete_entries(
    document: ClausewitzDocument,
    *,
    key_pattern: str,
    ancestor_suffix_pattern: str,
    exclude_key_patterns: Iterable[str],
) -> int:
    count = _count_entries(
        document,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
        operator=None,
        numeric=False,
        require_block=False,
    )
    if count > 0:
        document.delete_entries(
            key_pattern=key_pattern,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=tuple(exclude_key_patterns),
        )
    return count


def insert_entries_end_of_blocks(
    document: ClausewitzDocument,
    *,
    key_pattern: str,
    entry_raw: str,
    ancestor_suffix_pattern: str,
    exclude_key_patterns: Iterable[str],
) -> int:
    count = _count_entries(
        document,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
        operator=None,
        numeric=False,
        require_block=True,
    )
    if count > 0:
        document.insert_entries_end_of_blocks(
            key_pattern=key_pattern,
            entry_raw=entry_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=tuple(exclude_key_patterns),
        )
    return count


def _count_entries(
    document: ClausewitzDocument,
    *,
    key_pattern: str,
    ancestor_suffix_pattern: str,
    exclude_key_patterns: Iterable[str],
    operator: Operator | None,
    numeric: bool,
    require_block: bool,
) -> int:
    refs = find_entries(
        document.root,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=tuple(exclude_key_patterns),
    )
    count = 0
    for ref in refs:
        if operator is not None and ref.entry.operator != operator:
            continue
        if numeric:
            if not isinstance(ref.entry.value, ScalarValue):
                continue
            if _parse_number_raw(ref.entry.value.raw) is None:
                continue
        if require_block and not _is_block_value(ref.entry.value):
            continue
        count += 1
    return count


def _is_block_value(value: object) -> bool:
    if isinstance(value, Block):
        return True
    return isinstance(value, TaggedValue) and isinstance(value.value, Block)


def _parse_number_raw(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None
