"""CST-aware formatter with optional comment/trivia preservation."""

from __future__ import annotations

from clausewitz.core.cst import (
    CstBlock,
    CstComparison,
    CstEntry,
    CstList,
    CstListItem,
    CstScalar,
    CstTagged,
    CstValue,
    TriviaToken,
)
from clausewitz.format.policy import FormatPolicy
from clausewitz.format.lossless import print_cst


class ClausewitzCstFormatter:
    def __init__(
        self,
        policy: FormatPolicy | None = None,
        *,
        preserve_comments: bool = True,
        preserve_trivia: bool = False,
    ):
        self.policy = policy or FormatPolicy()
        self.preserve_comments = preserve_comments
        self.preserve_trivia = preserve_trivia

    def format(self, root: CstBlock) -> str:
        if self.preserve_trivia:
            return print_cst(root)
        out: list[str] = []
        self._emit_block(out, root, indent=0, braced=False)
        s = "".join(out)
        return s if s.endswith("\n") else s + "\n"

    def _emit_block(self, out: list[str], b: CstBlock, *, indent: int, braced: bool) -> None:
        if not braced:
            self._emit_comments(out, indent, b.leading_trivia)
            for e in b.entries:
                self._emit_entry(out, e, indent=indent)
            self._emit_comments(out, indent, b.close_trivia)
            return

        if self._can_inline_block(b):
            out.append(self._format_block_inline(b))
            return

        out.append("{\n")
        inner_indent = indent + self.policy.indent
        self._emit_comments(out, inner_indent, b.open_trivia)
        for e in b.entries:
            self._emit_entry(out, e, indent=inner_indent)
        self._emit_comments(out, inner_indent, b.close_trivia)
        out.append((" " * indent) + "}")

    def _emit_entry(self, out: list[str], e: CstEntry, *, indent: int) -> None:
        pre = list(e.leading_trivia) + list(e.between_key_op_trivia) + list(e.between_op_value_trivia)
        self._emit_comments(out, indent, pre)
        if e.key is None or e.operator is None or e.value is None:
            return
        out.append((" " * indent) + e.key.raw + " " + e.operator.raw + " ")
        out.append(self._format_value(e.value, indent=indent))
        out.append("\n")
        self._emit_comments(out, indent, e.trailing_trivia)

    def _format_value(self, v: CstValue, *, indent: int) -> str:
        if isinstance(v, CstScalar):
            return v.token.raw
        if isinstance(v, CstComparison):
            if v.operator is None or v.right is None:
                raise ValueError("Comparison missing operator or right scalar")
            return f"{v.left.raw} {v.operator.raw} {v.right.token.raw}"
        if isinstance(v, CstTagged):
            return self._format_tagged_value(v, indent=indent)
        if isinstance(v, CstList):
            return self._format_list(v, indent=indent)
        return self._format_block_value(v, indent=indent)

    def _format_brace_value(self, v: CstBlock | CstList, *, indent: int) -> str:
        if isinstance(v, CstBlock):
            return self._format_block_value(v, indent=indent)
        return self._format_list(v, indent=indent)

    def _format_block_value(self, b: CstBlock, *, indent: int) -> str:
        out: list[str] = []
        self._emit_block(out, b, indent=indent, braced=True)
        return "".join(out)

    def _format_block_inline(self, b: CstBlock) -> str:
        parts = [self._format_entry_inline(e) for e in b.entries]
        inner = " ".join(parts)
        return "{ " + inner + " }"

    def _format_entry_inline(self, e: CstEntry) -> str:
        if e.key is None or e.operator is None or e.value is None:
            raise ValueError("CST entry missing key/operator/value")
        return f"{e.key.raw} {e.operator.raw} {self._format_value(e.value, indent=0)}"

    def _format_list(self, lst: CstList, *, indent: int) -> str:
        if self._can_inline_list(lst):
            items = [self._format_value(it.value, indent=indent) for it in lst.items if it.value is not None]
            inner = " ".join(items)
            return "{ " + inner + " }"

        out: list[str] = []
        out.append("{\n")
        inner_indent = indent + self.policy.indent
        self._emit_comments(out, inner_indent, lst.open_trivia)
        for item in lst.items:
            self._emit_list_item(out, item, indent=inner_indent)
        self._emit_comments(out, inner_indent, lst.close_trivia)
        out.append((" " * indent) + "}")
        return "".join(out)

    def _emit_list_item(self, out: list[str], item: CstListItem, *, indent: int) -> None:
        self._emit_comments(out, indent, item.leading_trivia)
        if item.value is None:
            return
        out.append(" " * indent)
        out.append(self._format_value(item.value, indent=indent))
        out.append("\n")
        self._emit_comments(out, indent, item.trailing_trivia)

    def _can_inline_block(self, b: CstBlock) -> bool:
        if self._block_has_comments(b):
            return False
        if len(b.entries) == 0:
            return True
        if len(b.entries) > self.policy.inline_block_max_entries:
            return False
        return all(self._entry_is_scalarish(e) for e in b.entries)

    def _can_inline_list(self, lst: CstList) -> bool:
        if self._list_has_comments(lst):
            return False
        if len(lst.items) == 0:
            return True
        if len(lst.items) > self.policy.inline_list_max_items:
            return False
        return all(self._value_is_scalarish(it.value) for it in lst.items if it.value is not None)

    def _entry_is_scalarish(self, e: CstEntry) -> bool:
        if e.value is None:
            return False
        return self._value_is_scalarish(e.value)

    def _value_is_scalarish(self, v: CstValue) -> bool:
        return isinstance(v, (CstScalar, CstComparison))

    def _block_has_comments(self, b: CstBlock) -> bool:
        if not self.preserve_comments:
            return False
        if self._trivia_has_comments(b.leading_trivia + b.open_trivia + b.close_trivia):
            return True
        return any(self._entry_has_comments(e) for e in b.entries)

    def _entry_has_comments(self, e: CstEntry) -> bool:
        if not self.preserve_comments:
            return False
        if self._trivia_has_comments(
            e.leading_trivia + e.between_key_op_trivia + e.between_op_value_trivia + e.trailing_trivia
        ):
            return True
        if e.value is None:
            return False
        return self._value_has_comments(e.value)

    def _list_has_comments(self, lst: CstList) -> bool:
        if not self.preserve_comments:
            return False
        if self._trivia_has_comments(lst.open_trivia + lst.close_trivia):
            return True
        for it in lst.items:
            if self._trivia_has_comments(it.leading_trivia + it.trailing_trivia):
                return True
            if it.value is not None and self._value_has_comments(it.value):
                return True
        return False

    def _value_has_comments(self, v: CstValue) -> bool:
        if isinstance(v, CstBlock):
            return self._block_has_comments(v)
        if isinstance(v, CstList):
            return self._list_has_comments(v)
        if isinstance(v, CstTagged):
            if self._trivia_has_comments(v.between_tag_value_trivia):
                return True
            if v.value is None:
                return False
            return self._value_has_comments(v.value)
        return False

    def _trivia_has_comments(self, trivia: list[TriviaToken]) -> bool:
        if not self.preserve_comments:
            return False
        return any(self._is_comment(t.raw) for t in trivia)

    def _emit_comments(self, out: list[str], indent: int, trivia: list[TriviaToken]) -> None:
        if not self.preserve_comments:
            return
        for line in self._comment_lines(trivia):
            out.append((" " * indent) + self._normalize_comment_line(line) + "\n")

    def _comment_lines(self, trivia: list[TriviaToken]) -> list[str]:
        lines: list[str] = []
        for t in trivia:
            if not self._is_comment(t.raw):
                continue
            raw = t.raw.rstrip("\r\n")
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
        return lines

    def _is_comment(self, raw: str) -> bool:
        return raw.startswith("#")

    def _normalize_comment_line(self, line: str) -> str:
        if not line.startswith("#"):
            return line
        if line.startswith("##"):
            return line
        if len(line) == 1:
            return "#"
        if line[1] == " ":
            return line
        return "# " + line[1:].lstrip()

    def _format_tagged_value(self, v: CstTagged, *, indent: int) -> str:
        if v.value is None:
            raise ValueError("Tagged value missing braced value")
        comments = self._comment_lines(v.between_tag_value_trivia)
        if not self.preserve_comments or not comments:
            return f"{v.tag.raw} {self._format_brace_value(v.value, indent=indent)}"
        cont_indent = indent + self.policy.indent
        comment_block = "\n".join((" " * cont_indent) + self._normalize_comment_line(c) for c in comments)
        brace_val = self._format_brace_value(v.value, indent=0)
        brace_val = _indent_multiline(brace_val, cont_indent)
        return f"{v.tag.raw}\n{comment_block}\n{brace_val}"


def _indent_multiline(text: str, indent: int) -> str:
    pad = " " * indent
    lines = text.splitlines()
    return "\n".join(pad + ln if ln else ln for ln in lines)


__all__ = ["ClausewitzCstFormatter"]
