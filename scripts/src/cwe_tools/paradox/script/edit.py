from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy

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

type EntryContainer = Script | Block


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def scalar(
    value: str | int | float,
    *,
    quoted: bool = False,
) -> Scalar:
    return Scalar(str(value), quoted=quoted)


def quoted(value: str) -> Scalar:
    """Create a quoted scalar."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return Scalar(escaped, quoted=True)


def scalar_block(
    values: Iterable[str | int | float],
    *,
    quoted_values: bool = False,
) -> Block:
    return Block(
        [
            ValueEntry(
                scalar(value, quoted=quoted_values),
            )
            for value in values
        ]
    )


def assignment(
    key: str,
    value: Value,
    *,
    operator: str = "=",
) -> Assignment:
    return Assignment(
        key=key,
        value=value,
        operator=operator,
    )


def clone_script(script: Script) -> Script:
    """Deep-copy a parsed script before modifying it."""
    return deepcopy(script)


def clone_block(block: Block) -> Block:
    """Deep-copy a block before modifying it."""
    return deepcopy(block)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


def _entries(container: EntryContainer) -> list[Entry]:
    return container.entries


def _entry_index(
    container: EntryContainer,
    target: Entry,
) -> int:
    """Find an entry by identity, not structural equality."""
    for index, entry in enumerate(_entries(container)):
        if entry is target:
            return index

    raise ValueError("Entry does not belong to this container")


def append_entry(
    container: EntryContainer,
    entry: Entry,
) -> Entry:
    _entries(container).append(entry)
    return entry


def insert_entry(
    container: EntryContainer,
    index: int,
    entry: Entry,
) -> Entry:
    _entries(container).insert(index, entry)
    return entry


def remove_entry(
    container: EntryContainer,
    target: Entry,
) -> Entry:
    index = _entry_index(container, target)
    return _entries(container).pop(index)


def replace_entry(
    container: EntryContainer,
    target: Entry,
    replacement: Entry,
) -> Entry:
    index = _entry_index(container, target)
    _entries(container)[index] = replacement
    return replacement


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


def find_assignments(
    container: EntryContainer,
    key: str,
    *,
    include_commented: bool = False,
) -> list[Assignment]:
    matches: list[Assignment] = []

    for entry in _entries(container):
        if isinstance(entry, Assignment) and entry.key == key:
            matches.append(entry)
            continue

        if (
            include_commented
            and isinstance(entry, Commented)
            and isinstance(entry.entry, Assignment)
            and entry.entry.key == key
        ):
            matches.append(entry.entry)

    return matches


def find_assignment(
    container: EntryContainer,
    key: str,
    *,
    include_commented: bool = False,
) -> Assignment | None:
    matches = find_assignments(
        container,
        key,
        include_commented=include_commented,
    )
    return matches[-1] if matches else None


def require_assignment(
    container: EntryContainer,
    key: str,
    *,
    include_commented: bool = False,
) -> Assignment:
    result = find_assignment(
        container,
        key,
        include_commented=include_commented,
    )

    if result is None:
        raise KeyError(f"Missing assignment {key!r}")

    return result


def append_assignment(
    container: EntryContainer,
    key: str,
    value: Value,
    *,
    operator: str = "=",
) -> Assignment:
    result = Assignment(
        key=key,
        value=value,
        operator=operator,
    )
    _entries(container).append(result)
    return result


def insert_assignment(
    container: EntryContainer,
    index: int,
    key: str,
    value: Value,
    *,
    operator: str = "=",
) -> Assignment:
    result = Assignment(
        key=key,
        value=value,
        operator=operator,
    )
    _entries(container).insert(index, result)
    return result


def set_assignment(
    container: EntryContainer,
    key: str,
    value: Value,
    *,
    operator: str = "=",
) -> Assignment:
    """Update the final active assignment or append one if absent.

    This intentionally does not collapse repeated assignments.

    For repeatable keys such as:

        resource = { ... }
        resource = { ... }

    use append_assignment() or edit the desired Assignment directly.
    """
    existing = find_assignment(container, key)

    if existing is not None:
        existing.value = value
        existing.operator = operator
        return existing

    return append_assignment(
        container,
        key,
        value,
        operator=operator,
    )


def set_scalar_assignment(
    container: EntryContainer,
    key: str,
    value: str | int | float,
    *,
    quoted_value: bool = False,
    operator: str = "=",
) -> Assignment:
    return set_assignment(
        container,
        key,
        scalar(value, quoted=quoted_value),
        operator=operator,
    )


def remove_assignments(
    container: EntryContainer,
    key: str,
) -> list[Assignment]:
    """Remove active assignments while leaving all comments untouched."""
    removed: list[Assignment] = []
    remaining: list[Entry] = []

    for entry in _entries(container):
        if isinstance(entry, Assignment) and entry.key == key:
            removed.append(entry)
        else:
            remaining.append(entry)

    _entries(container)[:] = remaining
    return removed


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def get_block(
    container: EntryContainer,
    key: str,
) -> Block | None:
    result = find_assignment(container, key)

    if result is None:
        return None

    if isinstance(result.value, Block):
        return result.value

    return None


def require_block(
    container: EntryContainer,
    key: str,
) -> Block:
    result = get_block(container, key)

    if result is None:
        raise KeyError(f"Missing block assignment {key!r}")

    return result


def get_tagged_block(
    container: EntryContainer,
    key: str,
) -> TaggedBlock | None:
    result = find_assignment(container, key)

    if result is None:
        return None

    if isinstance(result.value, TaggedBlock):
        return result.value

    return None


# ---------------------------------------------------------------------------
# Anonymous block values
# ---------------------------------------------------------------------------


def value_entries(block: Block) -> list[ValueEntry]:
    return [entry for entry in block.entries if isinstance(entry, ValueEntry)]


def scalar_values(block: Block) -> list[str]:
    return [
        entry.value.text
        for entry in block.entries
        if isinstance(entry, ValueEntry) and isinstance(entry.value, Scalar)
    ]


def find_scalar_value(
    block: Block,
    value: str,
) -> ValueEntry | None:
    for entry in block.entries:
        if (
            isinstance(entry, ValueEntry)
            and isinstance(entry.value, Scalar)
            and entry.value.text == value
        ):
            return entry

    return None


def add_scalar_value(
    block: Block,
    value: str | int | float,
    *,
    quoted_value: bool = False,
) -> bool:
    text = str(value)

    if find_scalar_value(block, text) is not None:
        return False

    block.entries.append(
        ValueEntry(
            scalar(
                value,
                quoted=quoted_value,
            )
        )
    )
    return True


def remove_scalar_value(
    block: Block,
    value: str | int | float,
) -> bool:
    """Remove one matching scalar value.

    Comments and every other neighboring entry remain untouched.
    """
    target = find_scalar_value(block, str(value))

    if target is None:
        return False

    remove_entry(block, target)
    return True


def remove_all_scalar_values(
    block: Block,
    value: str | int | float,
) -> int:
    text = str(value)
    removed = 0
    remaining: list[Entry] = []

    for entry in block.entries:
        if (
            isinstance(entry, ValueEntry)
            and isinstance(entry.value, Scalar)
            and entry.value.text == text
        ):
            removed += 1
        else:
            remaining.append(entry)

    block.entries[:] = remaining
    return removed


def replace_scalar_value(
    block: Block,
    old: str | int | float,
    new: str | int | float,
    *,
    quoted_value: bool | None = None,
) -> bool:
    target = find_scalar_value(block, str(old))

    if target is None:
        return False

    if not isinstance(target.value, Scalar):
        return False

    quoted = target.value.quoted if quoted_value is None else quoted_value

    target.value = scalar(
        new,
        quoted=quoted,
    )
    return True


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def add_comment(
    container: EntryContainer,
    text: str,
    *,
    index: int | None = None,
) -> Comment:
    result = Comment(text)

    if index is None:
        _entries(container).append(result)
    else:
        _entries(container).insert(index, result)

    return result


def comment_out(entry: Entry) -> Commented:
    """Wrap an AST entry as intentionally commented-out content."""
    if isinstance(entry, Commented):
        return entry

    return Commented(entry)


def comment_out_entry(
    container: EntryContainer,
    target: Entry,
) -> Commented:
    """Comment out an entry in-place in its AST container."""
    if isinstance(target, Commented):
        return target

    commented = Commented(target)
    replace_entry(container, target, commented)
    return commented


def uncomment_entry(
    container: EntryContainer,
    target: Commented,
) -> Entry:
    """Restore a Commented entry to an active AST entry."""
    replacement = target.entry
    replace_entry(container, target, replacement)
    return replacement


def comment_out_assignment(
    container: EntryContainer,
    key: str,
    *,
    occurrence: int = -1,
) -> Commented:
    """Comment out one active assignment by key.

    occurrence=-1 selects the final matching assignment.
    """
    matches: list[tuple[Entry, Assignment]] = [
        (entry, entry)
        for entry in _entries(container)
        if isinstance(entry, Assignment) and entry.key == key
    ]

    if not matches:
        raise KeyError(f"Missing assignment {key!r}")

    try:
        entry, _assignment = matches[occurrence]
    except IndexError as exc:
        raise IndexError(
            f"Assignment {key!r} has only {len(matches)} occurrence(s)"
        ) from exc

    return comment_out_entry(container, entry)
