from __future__ import annotations

from fnmatch import fnmatchcase
from functools import lru_cache
import re
from typing import Iterator, Sequence

from clausewitz.edit.edits import AstEntryRef, CstEditSession
from clausewitz.model.ast import (
    AstValue,
    Block,
    ListValue,
    Operator,
    ScalarValue,
    TaggedValue,
)

_REGEX_PREFIX = "re:"

type Path = tuple[str, ...]


def parse_path(path: str | Sequence[str]) -> Path:
    if isinstance(path, str):
        return tuple(seg for seg in path.split(".") if seg)
    return tuple(path)


@lru_cache(maxsize=2048)
def _compile_regex(expr: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(expr, flags)


def _parse_regex_segment(seg: str) -> re.Pattern[str] | None:
    if seg.startswith(_REGEX_PREFIX):
        return _compile_regex(seg[len(_REGEX_PREFIX) :])

    if len(seg) >= 2 and seg[0] == "/" and seg.rfind("/") > 0:
        last = seg.rfind("/")
        pat = seg[1:last]
        flag_str = seg[last + 1 :]
        flags = 0
        for ch in flag_str:
            if ch == "i":
                flags |= re.IGNORECASE
            elif ch == "m":
                flags |= re.MULTILINE
            elif ch == "s":
                flags |= re.DOTALL
            elif ch == "":
                pass
            else:
                raise ValueError(f"Unknown regex flag: {ch} in segment {seg!r}")
        return _compile_regex(pat, flags)

    return None


def match_segment(pattern_seg: str, actual_seg: str) -> bool:
    if pattern_seg == "*":
        return True

    rx = _parse_regex_segment(pattern_seg)
    if rx is not None:
        return bool(rx.fullmatch(actual_seg))

    if any(ch in pattern_seg for ch in "*?[]"):
        return fnmatchcase(actual_seg, pattern_seg)

    return pattern_seg == actual_seg


def match_path_pattern(pattern: Sequence[str], actual: Sequence[str]) -> bool:
    p = tuple(pattern)
    a = tuple(actual)

    @lru_cache(maxsize=8192)
    def dp(i: int, j: int) -> bool:
        if i == len(p):
            return j == len(a)

        if p[i] == "**":
            if dp(i + 1, j):
                return True
            return j < len(a) and dp(i, j + 1)

        if j >= len(a):
            return False
        return match_segment(p[i], a[j]) and dp(i + 1, j + 1)

    return dp(0, 0)


def endswith_path_pattern(actual: Path, pattern: str | Sequence[str]) -> bool:
    pat = parse_path(pattern)
    if not pat:
        return True

    if "**" not in pat:
        if len(pat) > len(actual):
            return False
        return match_path_pattern(pat, actual[-len(pat) :])

    for start in range(0, len(actual) + 1):
        if match_path_pattern(pat, actual[start:]):
            return True
    return False


def _unwrap_block(v: AstValue) -> Block | None:
    if isinstance(v, Block):
        return v
    if isinstance(v, TaggedValue) and isinstance(v.value, Block):
        return v.value
    return None


def _unwrap_list(v: AstValue) -> ListValue | None:
    if isinstance(v, ListValue):
        return v
    if isinstance(v, TaggedValue) and isinstance(v.value, ListValue):
        return v.value
    return None


def walk_entries(root: Block) -> Iterator[AstEntryRef]:
    def _walk(b: Block, ancestors: Path) -> Iterator[AstEntryRef]:
        for e in b.entries:
            yield AstEntryRef(entry=e, ancestors=ancestors)
            child = _unwrap_block(e.value)
            if child is not None:
                yield from _walk(child, ancestors + (e.key,))

    yield from _walk(root, ())


def find_entries_by_path(root: Block, path: str | Sequence[str]) -> list[AstEntryRef]:
    p = parse_path(path)
    if not p:
        return []
    want_anc = p[:-1]
    want_key = p[-1]
    return [r for r in walk_entries(root) if r.entry.key == want_key and r.ancestors == want_anc]


def find_blocks_by_path(root: Block, path: str | Sequence[str]) -> list[Block]:
    out: list[Block] = []
    for r in find_entries_by_path(root, path):
        b = _unwrap_block(r.entry.value)
        if b is not None:
            out.append(b)
    return out


def find_lists_by_path(root: Block, path: str | Sequence[str]) -> list[ListValue]:
    out: list[ListValue] = []
    for r in find_entries_by_path(root, path):
        lst = _unwrap_list(r.entry.value)
        if lst is not None:
            out.append(lst)
    return out


def find_entries(
    root: Block,
    *,
    key_pattern: str,
    ancestor_suffix_pattern: str = "",
    exclude_key_patterns: Sequence[str] = (),
) -> list[AstEntryRef]:
    out: list[AstEntryRef] = []
    for ref in walk_entries(root):
        if not match_segment(key_pattern, ref.entry.key):
            continue
        if ancestor_suffix_pattern and not endswith_path_pattern(ref.ancestors, ancestor_suffix_pattern):
            continue
        if any(match_segment(p, ref.entry.key) for p in exclude_key_patterns):
            continue
        out.append(ref)
    return out


def replace_values(
    root: Block,
    *,
    key_pattern: str,
    new_raw: str,
    ancestor_suffix_pattern: str = "",
    exclude_key_patterns: Sequence[str] = (),
    operator: Operator | None = None,
    session: CstEditSession,
) -> None:
    for ref in find_entries(
        root,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
    ):
        if operator is not None and ref.entry.operator != operator:
            continue
        session.replace_entry_value_ast(ref, new_raw)


def delete_entries(
    root: Block,
    *,
    key_pattern: str,
    ancestor_suffix_pattern: str = "",
    exclude_key_patterns: Sequence[str] = (),
    session: CstEditSession,
) -> None:
    refs = find_entries(
        root,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
    )
    for ref in refs:
        session.delete_entry_ast(ref)


def insert_entries_end_of_blocks(
    root: Block,
    *,
    key_pattern: str,
    ancestor_suffix_pattern: str = "",
    exclude_key_patterns: Sequence[str] = (),
    entry_raw: str,
    session: CstEditSession,
) -> None:
    refs = find_entries(
        root,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
    )
    for ref in refs:
        try:
            session.insert_entry_end_of_block_ast(ref, entry_raw)
        except ValueError:
            continue


def _parse_number_raw(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _format_number_like(old_raw: str, new_value: float) -> str:
    s = old_raw.strip()
    if "." not in s:
        rounded = int(round(new_value))
        if abs(new_value - rounded) < 1e-9:
            return str(rounded)
        return str(new_value)

    decimals = len(s.split(".", 1)[1])
    return f"{new_value:.{decimals}f}"


def scale_numeric_values(
    root: Block,
    *,
    key_pattern: str,
    factor: float,
    ancestor_suffix_pattern: str = "",
    exclude_key_patterns: Sequence[str] = (),
    operator: Operator = "=",
    session: CstEditSession,
) -> None:
    for ref in find_entries(
        root,
        key_pattern=key_pattern,
        ancestor_suffix_pattern=ancestor_suffix_pattern,
        exclude_key_patterns=exclude_key_patterns,
    ):
        e = ref.entry
        if e.operator != operator:
            continue
        if not isinstance(e.value, ScalarValue):
            continue

        old_raw = e.value.raw
        old_num = _parse_number_raw(old_raw)
        if old_num is None:
            continue

        new_raw = _format_number_like(old_raw, old_num * factor)
        session.replace_entry_value_ast(ref, new_raw)


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
