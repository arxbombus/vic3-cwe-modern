# clausewitz/format/formatter.py
"""
AST -> Doc -> string formatter (Doc tree).

Canonical formatter:
- normalizes whitespace
- enforces max_width wrapping using Group/SoftLine decisions
- does NOT preserve original trivia (that's a later CST-aware reprinter feature)
"""

from __future__ import annotations

from dataclasses import dataclass

from clausewitz.format.doc import Doc, concat, group, indent, join, line, render, softline, text
from clausewitz.model.ast import (
    AstValue,
    Block,
    Comparison,
    Entry,
    ListValue,
    ScalarValue,
)


@dataclass(frozen=True, slots=True)
class FormatPolicy:
    max_width: int = 100
    indent: int = 4

    # Heuristics (canonical, not lossless):
    inline_list_max_items: int = 6
    inline_block_max_entries: int = 1


class ClausewitzFormatter:
    def __init__(self, policy: FormatPolicy | None = None):
        self.policy = policy or FormatPolicy()

    def format(self, root: Block) -> str:
        d = self._block(root, braced=False)
        # Ensure trailing newline like most formatters
        s = render(d, max_width=self.policy.max_width)
        return s if s.endswith("\n") else s + "\n"

    def _block(self, b: Block, *, braced: bool) -> Doc:
        entries = [self._entry(e) for e in b.entries]

        if not braced:
            # Root: entries separated by hard lines, no surrounding braces
            return join(line(), entries) if entries else text("")

        # Braced block: decide inline vs multiline via heuristic + Group
        if self._can_inline_block(b):
            inner = join(softline(), entries)
            return group(
                concat(text("{"), indent(concat(softline(), inner), by=self.policy.indent), softline(), text("}"))
            )

        inner = join(line(), entries)
        return concat(
            text("{"),
            indent(concat(line(), inner), by=self.policy.indent),
            line(),
            text("}"),
        )

    def _entry(self, e: Entry) -> Doc:
        # key <space> op <space> value
        return concat(
            text(e.key),
            text(" "),
            text(e.operator),
            text(" "),
            self._value(e.value),
        )

    def _value(self, v: AstValue) -> Doc:
        if isinstance(v, ScalarValue):
            return text(v.raw)
        if isinstance(v, Block):
            return self._block(v, braced=True)
        if isinstance(v, ListValue):
            return self._list(v)
        if isinstance(v, Comparison):
            return concat(text(v.key), text(" "), text(v.operator), text(" "), text(v.right.raw))
        # TaggedValue: tag <space> <braced value>
        return concat(text(v.tag), text(" "), self._brace_value(v.value))

    def _brace_value(self, v: Block | ListValue) -> Doc:
        if isinstance(v, Block):
            return self._block(v, braced=True)
        return self._list(v)

    def _list(self, lst: ListValue) -> Doc:
        items = [self._value(x) for x in lst.items]

        # Inline list candidate (group + softlines)
        if self._can_inline_list(lst):
            inner = join(softline(), items)
            return group(
                concat(
                    text("{"),
                    indent(concat(softline(), inner), by=self.policy.indent),
                    softline(),
                    text("}"),
                )
            )

        # Multiline list
        inner = join(line(), items)
        return concat(
            text("{"),
            indent(concat(line(), inner), by=self.policy.indent),
            line(),
            text("}"),
        )

    def _can_inline_list(self, lst: ListValue) -> bool:
        if len(lst.items) == 0:
            return True
        if len(lst.items) > self.policy.inline_list_max_items:
            return False
        # Inline only if everything is scalar-ish / short
        return all(isinstance(x, ScalarValue) for x in lst.items)

    def _can_inline_block(self, blk: Block) -> bool:
        if len(blk.entries) == 0:
            return True
        if len(blk.entries) > self.policy.inline_block_max_entries:
            return False
        # Inline only simple "key = scalar" style blocks
        return all(isinstance(e.value, ScalarValue) for e in blk.entries)


__all__ = ["ClausewitzFormatter", "FormatPolicy"]
