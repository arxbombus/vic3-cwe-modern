from __future__ import annotations

from collections import Counter
from typing import Any

from cwe_tools.paradox.script.ast import (
    Assignment,
    Block,
    Comment,
    Commented,
    Entry,
    Scalar,
    Script,
    TaggedBlock,
    Value,
    ValueEntry,
)


def to_python(script: Script) -> dict[str, Any]:
    """Convert a Script AST into convenient nested Python values.

    This representation is intentionally lossy and intended for inspection.

    - Comments are omitted.
    - Repeated assignments become lists.
    - Anonymous block values become Python lists.
    - Mixed blocks store anonymous values under ``__values__``.
    - Tagged blocks use ``__tag__`` and ``__value__``.
    - Commented-out AST entries are exposed under ``__commented__``.
    """
    return _entries_to_mapping(script.entries)


def _entries_to_mapping(entries: list[Entry]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    assignment_counts = Counter(
        entry.key for entry in entries if isinstance(entry, Assignment)
    )

    anonymous_values: list[Any] = []
    commented_values: list[Any] = []

    for entry in entries:
        if isinstance(entry, Comment):
            continue

        if isinstance(entry, Assignment):
            value = _value_to_python(entry.value)

            if assignment_counts[entry.key] == 1:
                result[entry.key] = value
            else:
                repeated = result.setdefault(entry.key, [])
                assert isinstance(repeated, list)
                repeated.append(value)

            continue

        if isinstance(entry, ValueEntry):
            anonymous_values.append(_value_to_python(entry.value))
            continue

        if isinstance(entry, Commented):
            commented_values.append(_entry_to_python(entry.entry))
            continue

        raise TypeError(f"Unsupported AST entry: {type(entry).__name__}")

    if anonymous_values:
        result["__values__"] = anonymous_values

    if commented_values:
        result["__commented__"] = commented_values

    return result


def _entry_to_python(entry: Entry) -> Any:
    if isinstance(entry, Assignment):
        return {
            entry.key: _value_to_python(entry.value),
        }

    if isinstance(entry, ValueEntry):
        return _value_to_python(entry.value)

    if isinstance(entry, Comment):
        return {
            "__comment__": entry.text,
        }

    if isinstance(entry, Commented):
        return {
            "__commented__": _entry_to_python(entry.entry),
        }

    raise TypeError(f"Unsupported AST entry: {type(entry).__name__}")


def _value_to_python(value: Value) -> Any:
    if isinstance(value, Scalar):
        return _scalar_to_python(value)

    if isinstance(value, Block):
        return _block_to_python(value)

    if isinstance(value, TaggedBlock):
        return {
            "__tag__": value.tag,
            "__value__": _block_to_python(value.block),
        }

    raise TypeError(f"Unsupported AST value: {type(value).__name__}")


def _block_to_python(block: Block) -> Any:
    assignments = [entry for entry in block.entries if isinstance(entry, Assignment)]

    values = [entry for entry in block.entries if isinstance(entry, ValueEntry)]

    # Pure value block:
    #
    # provinces = { "x123" "x456" }
    #
    # -> ["x123", "x456"]
    if values and not assignments:
        return [_value_to_python(entry.value) for entry in values]

    # Empty block, ignoring normal comments.
    if not assignments and not values:
        remaining = [entry for entry in block.entries if isinstance(entry, Commented)]

        if not remaining:
            return []

    # Assignment block:
    #
    # capped_resources = {
    #     building_coal_mine = 10
    # }
    #
    # or a mixed assignment/value block.
    return _entries_to_mapping(block.entries)


def _scalar_to_python(scalar: Scalar) -> Any:
    text = scalar.text

    if scalar.quoted:
        return text

    lowered = text.lower()

    if lowered == "yes":
        return True

    if lowered == "no":
        return False

    try:
        return int(text)
    except ValueError:
        pass

    try:
        return float(text)
    except ValueError:
        pass

    return text
