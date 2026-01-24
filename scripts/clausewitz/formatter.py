"""Formatter for Clausewitz documents in v2."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from clausewitz.document import ClausewitzDocument
from clausewitz.nodes import (
    ClausewitzBlock,
    ClausewitzComparison,
    ClausewitzEntry,
    ClausewitzList,
    ClausewitzListItem,
    ClausewitzScalarValue,
    ClausewitzValue,
)


@dataclass
class ClausewitzFormatter:
    indent: str = "\t"
    inline_braces: bool = True
    mode: Literal["format", "preserve"] = "format"

    def format_document(self, document: ClausewitzDocument) -> str:
        if self.mode == "preserve":
            return self._format_block_contents_preserve(document.root)
        lines: list[str] = []
        for entry in document.entries():
            lines.extend(self.format_entry(entry, 0))
        return "\n".join(lines) + "\n"

    def format_block(
        self, name: str, block: ClausewitzBlock, level: int = 0
    ) -> list[str]:
        if self.inline_braces and self._can_inline_block(block):
            inline_content = " ".join(
                self._format_inline_entry(entry.key, entry.value)
                for entry in block.entries
            )
            return [f"{self._indent(level)}{name} = {{ {inline_content} }}"]

        header = f"{self._indent(level)}{name} = {{"
        lines = [header]
        for entry in block.entries:
            lines.extend(self.format_entry(entry, level + 1))
        lines.append(f"{self._indent(level)}}}")
        return lines

    def format_entry(self, entry: ClausewitzEntry, level: int) -> list[str]:
        if self.mode == "preserve":
            return [self._format_entry_preserve(entry)]
        value = entry.value
        if isinstance(value, ClausewitzBlock):
            name = entry.key if entry.key is not None else ""
            return self.format_block(name, value, level)
        if isinstance(value, ClausewitzList):
            return self._format_list(entry.key, value, level)
        if isinstance(value, ClausewitzComparison):
            return [f"{self._indent(level)}{self._format_comparison(value)}"]
        return [f"{self._indent(level)}{entry.key} = {self._format_scalar(value)}"]

    def _format_list(self, key: str, value: ClausewitzList, level: int) -> list[str]:
        if not value.values:
            return [f"{self._indent(level)}{key} = {{}}"]
        if self.inline_braces and self._can_inline_list(value):
            inline = " ".join(
                self._format_scalar(item)
                if not isinstance(item, ClausewitzBlock)
                else self._format_inline_block(item)
                for item in value.values
            )
            return [f"{self._indent(level)}{key} = {{ {inline} }}"]

        lines: list[str] = [f"{self._indent(level)}{key} = {{"]
        for item in value.values:
            if isinstance(item, ClausewitzBlock):
                lines.append(f"{self._indent(level + 1)}{{")
                for entry in item.entries:
                    lines.extend(self.format_entry(entry, level + 2))
                lines.append(f"{self._indent(level + 1)}}}")
            elif isinstance(item, ClausewitzComparison):
                lines.append(
                    f"{self._indent(level + 1)}{self._format_comparison(item)}"
                )
            else:
                lines.append(f"{self._indent(level + 1)}{self._format_scalar(item)}")
        lines.append(f"{self._indent(level)}}}")
        return lines

    def _format_scalar(self, value: ClausewitzValue) -> str:
        if isinstance(value, ClausewitzScalarValue):
            if self.mode == "preserve":
                return value.raw
            return self._format_scalar(value.value)
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, str):
            if self._needs_quotes(value):
                return f'"{value.replace('"', '\\"')}"'
            return value
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
        return str(value)

    def _indent(self, level: int) -> str:
        return "" if level <= 0 else self.indent * level

    def _needs_quotes(self, text: str) -> bool:
        if not text:
            return True
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./@:[]^?|"
        )
        return any(ch.isspace() or ch not in allowed for ch in text)

    def _format_comparison(self, comparison: ClausewitzComparison) -> str:
        right = comparison.right
        if isinstance(right, ClausewitzComparison):
            raise ValueError("Nested comparisons are not supported")
        if isinstance(right, ClausewitzBlock):
            raise ValueError("Comparison right-hand side cannot be a block")
        right_str = self._format_scalar(right)
        return f"{comparison.left} {comparison.operator} {right_str}"

    def _can_inline_block(self, block: ClausewitzBlock) -> bool:
        if not block.entries:
            return False
        if len(block.entries) == 1:
            return self._is_scalar_value(block.entries[0].value)
        if len(block.entries) == 2:
            return all(self._is_numeric_scalar(entry.value) for entry in block.entries)
        return False

    def _format_inline_entry(self, key: str, value: ClausewitzValue) -> str:
        if isinstance(value, ClausewitzBlock) and self._can_inline_block(value):
            inner = self._format_inline_block(value)
            return f"{key} = {{ {inner} }}"
        if isinstance(value, ClausewitzList) and self._can_inline_list(value):
            inner = " ".join(self._format_scalar(v) for v in value.values)
            return f"{key} = {{ {inner} }}"
        if isinstance(value, ClausewitzComparison):
            return f"{key} = {self._format_comparison(value)}"
        return f"{key} = {self._format_scalar(value)}"

    def _can_inline_list(self, value: ClausewitzList) -> bool:
        if not value.values or len(value.values) > 8:
            return False
        return all(self._is_inline_scalar(item) for item in value.values)

    def _format_inline_block(self, block: ClausewitzBlock) -> str:
        if not self._can_inline_block(block):
            raise ValueError("Cannot inline complex block")
        parts = [
            f"{entry.key} = {self._format_scalar(entry.value)}"
            for entry in block.entries
        ]
        return " ".join(parts)

    def _is_scalar_value(self, value: ClausewitzValue) -> bool:
        return not isinstance(
            value, (ClausewitzBlock, ClausewitzList, ClausewitzComparison)
        )

    def _is_inline_scalar(self, value: ClausewitzValue) -> bool:
        if isinstance(value, ClausewitzScalarValue):
            return self._is_inline_scalar(value.value)
        return isinstance(value, (str, int, float, bool))

    def _is_numeric_scalar(self, value: ClausewitzValue) -> bool:
        if not self._is_scalar_value(value):
            return False
        if isinstance(value, ClausewitzScalarValue):
            return self._is_numeric_scalar(value.value)
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            if value.startswith("@"):  # constant/coordinate reference
                return True
            return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value))
        return False

    def _format_entry_preserve(self, entry: ClausewitzEntry) -> str:
        value = entry.value
        if isinstance(value, ClausewitzBlock):
            value_text = self._format_block_value_preserve(value)
        elif isinstance(value, ClausewitzList):
            value_text = self._format_list_value_preserve(value)
        elif isinstance(value, ClausewitzComparison):
            right_text = self._format_scalar(value.right)
            return (
                f"{entry.leading_trivia}{value.left}{entry.key_trivia}"
                f"{entry.operator}{entry.operator_trivia}{right_text}{entry.trailing_trivia}"
            )
        else:
            value_text = self._format_scalar(value)
        return (
            f"{entry.leading_trivia}{entry.key}{entry.key_trivia}"
            f"{entry.operator}{entry.operator_trivia}{value_text}{entry.trailing_trivia}"
        )

    def _format_block_contents_preserve(self, block: ClausewitzBlock) -> str:
        parts = [block.leading_trivia]
        for entry in block.entries:
            parts.append(self._format_entry_preserve(entry))
        parts.append(block.trailing_trivia)
        return "".join(parts)

    def _format_block_value_preserve(self, block: ClausewitzBlock) -> str:
        return "{" + self._format_block_contents_preserve(block) + "}"

    def _format_list_value_preserve(self, value: ClausewitzList) -> str:
        parts = ["{", value.open_trivia]
        for item in value.items:
            parts.append(self._format_list_item_preserve(item))
        parts.append(value.close_trivia)
        parts.append("}")
        return "".join(parts)

    def _format_list_item_preserve(self, item: ClausewitzListItem) -> str:
        value = item.value
        if isinstance(value, ClausewitzBlock):
            value_text = self._format_block_value_preserve(value)
        elif isinstance(value, ClausewitzList):
            value_text = self._format_list_value_preserve(value)
        elif isinstance(value, ClausewitzComparison):
            right_text = self._format_scalar(value.right)
            value_text = (
                f"{value.left}{item.key_trivia}{value.operator}"
                f"{item.operator_trivia}{right_text}"
            )
        else:
            value_text = self._format_scalar(value)
        return f"{item.leading_trivia}{value_text}{item.trailing_trivia}"
