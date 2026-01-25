# patcher.py
from __future__ import annotations

from dataclasses import dataclass
from typing import overload

from clausewitz.edit.edits import Delete, Insert, Replace
from clausewitz.format.formatter import ClausewitzFormatter, FormatPolicy
from clausewitz.model.ast import AstValue, Block, Entry, ListValue, ScalarValue

Span = tuple[int, int]

MAX_WIDTH_DEFAULT = 100
INDENT_DEFAULT = 4


@dataclass(frozen=True, slots=True)
class PatchPolicy:
    indent: int = INDENT_DEFAULT
    newline: str = "\n"
    format_policy: FormatPolicy = FormatPolicy(max_width=MAX_WIDTH_DEFAULT, indent=INDENT_DEFAULT)


def _line_indent_at(source: str, pos: int) -> str:
    nl = source.rfind("\n", 0, pos)
    line_start = 0 if nl == -1 else nl + 1
    i = line_start
    while i < len(source) and source[i] in (" ", "\t"):
        i += 1
    return source[line_start:i]


def _indent_multiline(snippet: str, *, indent: str, newline: str) -> str:
    snippet = snippet.strip("\r\n")
    lines = snippet.splitlines()
    body = newline.join((indent + ln.lstrip(" \t") if ln.strip() else ln) for ln in lines)
    return newline + body + newline


def _formatter(policy: PatchPolicy) -> ClausewitzFormatter:
    return ClausewitzFormatter(policy.format_policy)


def entry_to_snippet(e: Entry, *, policy: PatchPolicy = PatchPolicy()) -> str:
    fmt = _formatter(policy)
    tmp = Block(entries=[e])
    return fmt.format(tmp).strip("\r\n")


def list_item_to_snippet(v: AstValue, *, policy: PatchPolicy = PatchPolicy()) -> str:
    fmt = _formatter(policy)
    tmp = Block(entries=[Entry(key="x", operator="=", value=ListValue(items=[v]))])
    rendered = fmt.format(tmp)
    lo = rendered.find("{")
    hi = rendered.rfind("}")
    if lo == -1 or hi == -1 or hi <= lo:
        raise ValueError("Unexpected formatter output for list-item snippet")
    return rendered[lo + 1 : hi].strip()


def replace_scalar_raw_with(node: ScalarValue, new_raw: str) -> Replace:
    if node.origin is None:
        raise ValueError("ScalarValue has no origin")
    s, e = node.origin
    return Replace(s, e, new_raw)


def replace_scalar_raw(node: ScalarValue) -> Replace:
    return replace_scalar_raw_with(node, node.raw)


def replace_entry_value(entry: Entry, new_value_raw: str) -> Replace:
    if entry.value_origin is None:
        raise ValueError("Entry has no value_origin")
    s, e = entry.value_origin
    return Replace(s, e, new_value_raw)


@overload
def insert_entry_end_of_block_ast(
    source: str,
    block: Block,
    entry: str,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert: ...


@overload
def insert_entry_end_of_block_ast(
    source: str,
    block: Block,
    entry: Entry,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert: ...


def insert_entry_end_of_block_ast(
    source: str,
    block: Block,
    entry: str | Entry,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert:
    close_span: Span | None = block.close_brace_origin
    if close_span is None:
        raise ValueError("Block is missing close_brace_origin")
    close_pos = close_span[0]

    snippet = entry_to_snippet(entry, policy=policy) if isinstance(entry, Entry) else entry.strip()
    close_indent = _line_indent_at(source, close_pos)
    content_indent = close_indent + (" " * policy.indent)
    text = _indent_multiline(snippet, indent=content_indent, newline=policy.newline)
    return Insert(close_pos, text)


@overload
def insert_item_end_of_list_ast(
    source: str,
    lst: ListValue,
    item: str,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert: ...


@overload
def insert_item_end_of_list_ast(
    source: str,
    lst: ListValue,
    item: AstValue,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert: ...


def insert_item_end_of_list_ast(
    source: str,
    lst: ListValue,
    item: str | AstValue,
    *,
    policy: PatchPolicy = PatchPolicy(),
) -> Insert:
    close_span: Span | None = lst.close_brace_origin
    if close_span is None:
        raise ValueError("ListValue is missing close_brace_origin")
    close_pos = close_span[0]

    snippet = list_item_to_snippet(item, policy=policy) if not isinstance(item, str) else item.strip()
    close_indent = _line_indent_at(source, close_pos)
    content_indent = close_indent + (" " * policy.indent)
    text = _indent_multiline(snippet, indent=content_indent, newline=policy.newline)
    return Insert(close_pos, text)


def delete_entry(entry: Entry) -> Delete:
    if entry.origin is None:
        raise ValueError("Entry has no origin")
    s, e = entry.origin
    return Delete(s, e)


__all__ = [
    "PatchPolicy",
    "delete_entry",
    "entry_to_snippet",
    "insert_entry_end_of_block_ast",
    "insert_item_end_of_list_ast",
    "list_item_to_snippet",
    "replace_entry_value",
    "replace_scalar_raw",
    "replace_scalar_raw_with",
]
