"""Lossless CST -> text printer (replays trivia + token.raw exactly)."""

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
from clausewitz.core.lexer import Token


def _emit_trivia(out: list[str], trivia: list[TriviaToken]) -> None:
    for t in trivia:
        out.append(t.raw)


def _emit_token(out: list[str], tok: Token | None, *, what: str) -> None:
    if tok is None:
        raise ValueError(f"Missing token for {what}")
    out.append(tok.raw)


def print_cst(root: CstBlock) -> str:
    out: list[str] = []
    _print_block(out, root)
    return "".join(out)


def _print_value(out: list[str], v: CstValue) -> None:
    if isinstance(v, CstScalar):
        _emit_token(out, v.token, what="scalar.token")
        return

    if isinstance(v, CstTagged):
        _emit_token(out, v.tag, what="tagged.tag")
        _emit_trivia(out, v.between_tag_value_trivia)
        if v.value is None:
            raise ValueError("Tagged value missing braced value")
        _print_value(out, v.value)  # value is a braced value node
        return

    if isinstance(v, CstComparison):
        _emit_token(out, v.left, what="comparison.left")
        _emit_trivia(out, v.between_left_op_trivia)
        _emit_token(out, v.operator, what="comparison.operator")
        _emit_trivia(out, v.between_op_right_trivia)
        if v.right is None:
            raise ValueError("Comparison missing right scalar")
        _emit_token(out, v.right.token, what="comparison.right.token")
        return

    if isinstance(v, CstList):
        _emit_token(out, v.open_brace, what="list.open_brace")
        _emit_trivia(out, v.open_trivia)
        for item in v.items:
            _print_list_item(out, item)
        _emit_trivia(out, v.close_trivia)
        _emit_token(out, v.close_brace, what="list.close_brace")
        return

    # Block
    _print_block(out, v)
    return


def _print_list_item(out: list[str], item: CstListItem) -> None:
    _emit_trivia(out, item.leading_trivia)
    if item.value is None:
        raise ValueError("List item missing value")
    _print_value(out, item.value)
    _emit_trivia(out, item.trailing_trivia)


def _print_entry(out: list[str], e: CstEntry) -> None:
    _emit_trivia(out, e.leading_trivia)
    _emit_token(out, e.key, what="entry.key")
    _emit_trivia(out, e.between_key_op_trivia)
    _emit_token(out, e.operator, what="entry.operator")
    _emit_trivia(out, e.between_op_value_trivia)
    if e.value is None:
        raise ValueError("Entry missing value")
    _print_value(out, e.value)
    _emit_trivia(out, e.trailing_trivia)


def _print_block(out: list[str], b: CstBlock) -> None:
    _emit_trivia(out, b.leading_trivia)

    if b.open_brace is not None:
        _emit_token(out, b.open_brace, what="block.open_brace")
        _emit_trivia(out, b.open_trivia)

    for e in b.entries:
        _print_entry(out, e)

    _emit_trivia(out, b.close_trivia)

    if b.close_brace is not None:
        _emit_token(out, b.close_brace, what="block.close_brace")
