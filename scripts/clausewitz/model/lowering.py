"""
Lowering: CST -> AST with origin spans.

Option 3 depends on origins:
- We patch the original text at these ranges.
- Unchanged regions remain byte-identical.
"""

from __future__ import annotations

from typing import cast

from clausewitz.core.cst import (
    CstBlock,
    CstComparison,
    CstEntry,
    CstList,
    CstScalar,
    CstTagged,
    CstValue,
)
from clausewitz.core.lexer import Token, TokenType
from clausewitz.model.ast import (
    AstValue,
    Block,
    Comparison,
    Entry,
    ListValue,
    Operator,
    Origin,
    Scalar,
    ScalarValue,
    TaggedValue,
)

_VALID_OPERATORS: set[str] = {">", "<", ">=", "<=", "!=", "="}


def lower_root(cst_root: CstBlock) -> Block:
    return _lower_block(cst_root)


# -----------------------------------------------------------------------------
# Span helpers (CST -> (start,end))
# -----------------------------------------------------------------------------


def _tok_span(t: Token) -> Origin:
    return (t.start, t.end)


def _trivia_span(trivia: list[Token]) -> Origin | None:
    if not trivia:
        return None
    return (trivia[0].start, trivia[-1].end)


def _cst_value_span(v: CstValue) -> Origin:
    if isinstance(v, CstScalar):
        return _tok_span(v.token)
    if isinstance(v, CstBlock):
        return _cst_block_span(v)
    if isinstance(v, CstList):
        return _cst_list_span(v)
    if isinstance(v, CstComparison):
        # comparison inside list: from left token to right scalar
        if v.operator is None or v.right is None:
            # best-effort
            return _tok_span(v.left)
        return (_tok_span(v.left)[0], _tok_span(v.right.token)[1])
    else:
        # tagged brace value
        if v.value is None:
            return _tok_span(v.tag)
        vs = _cst_value_span(v.value)
        return (_tok_span(v.tag)[0], vs[1])


def _cst_entry_span(e: CstEntry) -> Origin:
    # Include leading/trailing trivia if present; else fall back to key/value spans
    if e.key is None or e.operator is None or e.value is None:
        # best-effort
        start = _trivia_span(e.leading_trivia)
        if start:
            return (start[0], start[1])
        return (0, 0)

    lead = _trivia_span(e.leading_trivia)
    tail = _trivia_span(e.trailing_trivia)
    key_s = _tok_span(e.key)
    val_s = _cst_value_span(e.value)
    start = lead[0] if lead else key_s[0]
    end = tail[1] if tail else val_s[1]
    return (start, end)


def _cst_block_span(b: CstBlock) -> Origin:
    if b.open_brace is None or b.close_brace is None:
        # root block: span from first entry/trivia to last trivia
        if b.entries:
            s = _cst_entry_span(b.entries[0])[0]
            e = _cst_entry_span(b.entries[-1])[1]
            # include trailing trivia if exists
            t = _trivia_span(b.close_trivia)
            if t:
                e = max(e, t[1])
            return (s, e)
        # just trivia
        t = _trivia_span(b.leading_trivia) or _trivia_span(b.close_trivia)
        return t if t else (0, 0)

    # braced span includes braces
    return (b.open_brace.start, b.close_brace.end)


def _cst_list_span(lst: CstList) -> Origin:
    if lst.close_brace is None:
        return (lst.open_brace.start, lst.open_brace.end)
    return (lst.open_brace.start, lst.close_brace.end)


# -----------------------------------------------------------------------------
# Lowering
# -----------------------------------------------------------------------------


def _lower_block(node: CstBlock) -> Block:
    out = Block(origin=_cst_block_span(node))
    for e in node.entries:
        lowered = _lower_entry(e)
        if lowered is not None:
            out.entries.append(lowered)
    return out


def _lower_entry(node: CstEntry) -> Entry | None:
    if node.key is None or node.operator is None or node.value is None:
        return None

    key = node.key.raw
    op = _lower_operator(node.operator)
    value = _lower_value(node.value)

    entry = Entry(
        key=key,
        operator=op,
        value=value,
        origin=_cst_entry_span(node),
        key_origin=_tok_span(node.key),
        op_origin=_tok_span(node.operator),
        value_origin=_cst_value_span(node.value),
    )
    return entry


def _lower_value(node: CstValue) -> AstValue:
    if isinstance(node, CstScalar):
        return _lower_scalar(node)
    if isinstance(node, CstBlock):
        return _lower_block(node)
    if isinstance(node, CstList):
        return _lower_list(node)
    if isinstance(node, CstComparison):
        return _lower_list_comparison(node)
    else:
        # CstTagged
        return _lower_tagged(node)


def _lower_list(node: CstList) -> ListValue:
    items: list[AstValue] = []
    for it in node.items:
        if it.value is None:
            continue
        items.append(_lower_value(it.value))
    return ListValue(items=items, origin=_cst_list_span(node))


def _lower_list_comparison(node: CstComparison) -> Comparison:
    if node.operator is None or node.right is None:
        raise ValueError("CstComparison missing operator or right scalar")
    op = _lower_operator(node.operator)
    if op == "=":
        raise ValueError("ListComparison operator must not be '='")
    left_key = node.left.raw
    right = _lower_scalar(node.right)
    org = _cst_value_span(node)
    return Comparison(key=left_key, operator=op, right=right, origin=org)


def _lower_tagged(node: CstTagged) -> TaggedValue:
    if node.value is None:
        raise ValueError("CstTagged missing braced value")
    tag = node.tag.raw
    inner = _lower_value(node.value)
    if not isinstance(inner, (Block, ListValue)):
        raise TypeError("TaggedValue must wrap a braced AST value (Block or ListValue)")
    org = _cst_value_span(node)
    return TaggedValue(
        tag=tag,
        value=inner,
        origin=org,
        tag_origin=_tok_span(node.tag),
        value_origin=inner.origin,
    )


def _lower_scalar(node: CstScalar) -> ScalarValue:
    tok = node.token
    v = tok.value

    if tok.type == TokenType.STRING:
        if not isinstance(v, str):
            raise TypeError("STRING token must have string value")
        return ScalarValue(value=v, raw=tok.raw, origin=_tok_span(tok))

    if tok.type == TokenType.NUMBER:
        if not isinstance(v, (int, float)):
            raise TypeError("NUMBER token must have int/float value")
        return ScalarValue(value=cast(Scalar, v), raw=tok.raw, origin=_tok_span(tok))

    if tok.type == TokenType.BOOLEAN:
        if not isinstance(v, bool):
            raise TypeError("BOOLEAN token must have bool value")
        return ScalarValue(value=v, raw=tok.raw, origin=_tok_span(tok))

    if tok.type in {TokenType.IDENTIFIER, TokenType.KEYWORD, TokenType.MODIFIER, TokenType.TRIGGER}:
        if not isinstance(v, str):
            raise TypeError("Identifier-like token must have string value")
        return ScalarValue(value=v, raw=tok.raw, origin=_tok_span(tok))

    raise TypeError(f"Unexpected scalar token type: {tok.type}")


def _lower_operator(tok: Token) -> Operator:
    if tok.type != TokenType.OPERATOR:
        raise TypeError("Operator token expected")
    op_raw = tok.raw
    if op_raw not in _VALID_OPERATORS:
        raise ValueError(f"Invalid operator: {op_raw}")
    return cast(Operator, op_raw)


__all__ = ["lower_root"]
