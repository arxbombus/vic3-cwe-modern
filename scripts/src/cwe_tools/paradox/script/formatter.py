from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class FormatOptions:
    indent: str = "    "
    max_inline_width: int = 120


def _format_scalar(value: Scalar) -> str:
    if not value.quoted:
        return value.text
    return f'"{value.text}"'


def _inline_block(block: Block, *, options: FormatOptions) -> str | None:
    parts: list[str] = []
    for entry in block.entries:
        if not isinstance(entry, ValueEntry) or not isinstance(entry.value, Scalar):
            return None
        parts.append(_format_scalar(entry.value))
    candidate = "{ " + " ".join(parts) + " }"
    return candidate if len(candidate) <= options.max_inline_width else None


def _format_value(value: Value, level: int, options: FormatOptions) -> list[str]:
    if isinstance(value, Scalar):
        return [_format_scalar(value)]
    if isinstance(value, TaggedBlock):
        rendered = _format_block(value.block, level, options)
        rendered[0] = f"{value.tag}{rendered[0]}"
        return rendered
    return _format_block(value, level, options)


def _format_block(block: Block, level: int, options: FormatOptions) -> list[str]:
    inline = _inline_block(block, options=options)
    if inline is not None:
        return [inline]

    lines = ["{"]
    for entry in block.entries:
        lines.extend(_format_entry(entry, level + 1, options))
    lines.append(f"{options.indent * level}}}")
    return lines


def _prefix_multiline(prefix: str, value_lines: list[str], indent: str) -> list[str]:
    if len(value_lines) == 1:
        return [prefix + value_lines[0]]
    return [prefix + value_lines[0], *value_lines[1:]]


def _format_entry(entry: Entry, level: int, options: FormatOptions) -> list[str]:
    indent = options.indent * level

    if isinstance(entry, Comment):
        return [f"{indent}# {entry.text}".rstrip()]

    if isinstance(entry, Commented):
        raw = _format_entry(entry.entry, level, options)
        return [
            f"{indent}# {line[len(indent) :]}"
            if line.startswith(indent)
            else f"{indent}# {line}"
            for line in raw
        ]

    if isinstance(entry, ValueEntry):
        value_lines = _format_value(entry.value, level, options)
        return _prefix_multiline(indent, value_lines, indent)

    value_lines = _format_value(entry.value, level, options)
    prefix = f"{indent}{entry.key} {entry.operator} "
    return _prefix_multiline(prefix, value_lines, indent)


def format_script(script: Script, *, options: FormatOptions | None = None) -> str:
    opts = options or FormatOptions()
    lines: list[str] = []
    for index, entry in enumerate(script.entries):
        if (
            index
            and isinstance(entry, Assignment)
            and isinstance(script.entries[index - 1], Assignment)
        ):
            # Top-level definitions are easier to scan with one blank line between them.
            lines.append("")
        lines.extend(_format_entry(entry, 0, opts))
    return "\n".join(lines).rstrip() + "\n"
