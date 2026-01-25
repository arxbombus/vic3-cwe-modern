# ast.py
"""Semantic AST for Clausewitz scripts (no trivia; designed for manipulation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type Scalar = str | int | float | bool
type Operator = Literal[">", "<", ">=", "<=", "!=", "="]

# [start, end) byte offsets into the original source text
type Origin = tuple[int, int]


@dataclass(slots=True)
class ScalarValue:
    value: Scalar
    raw: str
    origin: Origin | None = None


@dataclass(slots=True)
class Entry:
    key: str
    operator: Operator
    value: AstValue
    origin: Origin | None = None
    # Convenient sub-spans for patching (optional but useful)
    key_origin: Origin | None = None
    op_origin: Origin | None = None
    value_origin: Origin | None = None


@dataclass(slots=True)
class Block:
    entries: list[Entry] = field(default_factory=list[Entry])
    origin: Origin | None = None
    close_brace_origin: tuple[int, int] | None = None


@dataclass(slots=True)
class ListValue:
    items: list[AstValue] = field(default_factory=list["AstValue"])
    origin: Origin | None = None
    close_brace_origin: tuple[int, int] | None = None


@dataclass(slots=True)
class Comparison:
    key: str
    operator: Operator
    right: ScalarValue
    origin: Origin | None = None


@dataclass(slots=True)
class TaggedValue:
    """
    Tagged brace value like: rgb { 255 0 0 }
    Not a call, just a syntactic tagged-brace construct.
    """

    tag: str
    value: AstBraceValue
    origin: Origin | None = None
    tag_origin: Origin | None = None
    value_origin: Origin | None = None


type AstBraceValue = Block | ListValue
type AstValue = ScalarValue | Block | ListValue | Comparison | TaggedValue

__all__ = [
    "AstBraceValue",
    "AstValue",
    "Block",
    "Comparison",
    "Entry",
    "ListValue",
    "Operator",
    "Origin",
    "Scalar",
    "ScalarValue",
    "TaggedValue",
]
