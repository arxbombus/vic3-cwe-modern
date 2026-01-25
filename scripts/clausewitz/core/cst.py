"""Lossless CST for Clausewitz scripts (tokens + trivia preserved)."""

from __future__ import annotations

from dataclasses import dataclass, field

from clausewitz.core.lexer import Token, TokenType

type TriviaToken = Token  # TokenType.TRIVIA only

SCALAR_TOKENS = {
    TokenType.STRING,
    TokenType.NUMBER,
    TokenType.BOOLEAN,
    TokenType.IDENTIFIER,
    TokenType.KEYWORD,
    TokenType.MODIFIER,
    TokenType.TRIGGER,
}

# Keys are allowed to be NUMBER in some Clausewitz contexts (e.g. scripted arrays / indices)
KEY_TOKENS = {
    TokenType.IDENTIFIER,
    TokenType.KEYWORD,
    TokenType.MODIFIER,
    TokenType.TRIGGER,
    TokenType.NUMBER,
}

TAG_TOKENS = {
    TokenType.IDENTIFIER,
    TokenType.KEYWORD,
    TokenType.MODIFIER,
    TokenType.TRIGGER,
}


# -----------------------------------------------------------------------------


def _assert_trivia(tokens: list[Token]) -> None:
    for t in tokens:
        if t.type != TokenType.TRIVIA:
            raise TypeError("Expected only TRIVIA tokens in trivia lists")


def _assert_scalar_token(token: Token) -> None:
    if token.type not in SCALAR_TOKENS:
        raise TypeError(f"Invalid scalar token type: {token.type}")


def _assert_key_token(token: Token) -> None:
    if token.type not in KEY_TOKENS:
        raise TypeError(f"Invalid key token type: {token.type}")


def _assert_tag_token(token: Token) -> None:
    if token.type not in TAG_TOKENS:
        raise TypeError(f"Invalid tag token type: {token.type}")


def _assert_operator_token(token: Token) -> None:
    if token.type != TokenType.OPERATOR:
        raise TypeError(f"Invalid operator token type: {token.type}")


def _assert_open_brace(token: Token | None) -> None:
    if token is not None and token.type != TokenType.OPEN_BRACE:
        raise TypeError("Expected OPEN_BRACE or None")


def _assert_close_brace(token: Token | None) -> None:
    if token is not None and token.type != TokenType.CLOSE_BRACE:
        raise TypeError("Expected CLOSE_BRACE or None")


# -----------------------------------------------------------------------------
# Nodes
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class CstScalar:
    token: Token

    def __post_init__(self) -> None:
        _assert_scalar_token(self.token)


@dataclass(slots=True)
class CstComparison:
    """
    Comparison such as: { foo > 1 }.

    if = {
        start_date > 1836.1.1
    }

    Note: Entry-level comparisons (foo > 1 at block level) are represented as a normal CstEntry
    with operator != '=' and value being a scalar (or tagged brace, etc).
    """

    left: Token
    between_left_op_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    operator: Token | None = None  # OPERATOR token, value must be != '='
    between_op_right_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    right: CstScalar | None = None

    def __post_init__(self) -> None:
        _assert_key_token(self.left)
        _assert_trivia(self.between_left_op_trivia)
        _assert_trivia(self.between_op_right_trivia)
        if self.operator is not None:
            _assert_operator_token(self.operator)


@dataclass(slots=True)
class CstTagged:
    """Tagged brace value such as: rgb { 255 0 0 }."""

    tag: Token
    between_tag_value_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    value: CstList | CstBlock | None = None  # must be a braced value (list or block)

    def __post_init__(self) -> None:
        _assert_tag_token(self.tag)
        _assert_trivia(self.between_tag_value_trivia)


@dataclass(slots=True)
class CstEntry:
    leading_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    key: Token | None = None
    between_key_op_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    operator: Token | None = None
    between_op_value_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    value: CstValue | None = None
    trailing_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])

    def __post_init__(self) -> None:
        _assert_trivia(self.leading_trivia)
        _assert_trivia(self.between_key_op_trivia)
        _assert_trivia(self.between_op_value_trivia)
        _assert_trivia(self.trailing_trivia)
        if self.key is not None:
            _assert_key_token(self.key)
        if self.operator is not None:
            _assert_operator_token(self.operator)


@dataclass(slots=True)
class CstBlock:
    leading_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    open_brace: Token | None = None  # OPEN_BRACE if this is a braced block; None for root
    open_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    entries: list[CstEntry] = field(default_factory=list[CstEntry])
    close_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    close_brace: Token | None = None  # CLOSE_BRACE if braced; None for root

    def __post_init__(self) -> None:
        _assert_trivia(self.leading_trivia)
        _assert_trivia(self.open_trivia)
        _assert_trivia(self.close_trivia)
        _assert_open_brace(self.open_brace)
        _assert_close_brace(self.close_brace)


@dataclass(slots=True)
class CstListItem:
    leading_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    value: CstValue | None = None
    trailing_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])

    def __post_init__(self) -> None:
        _assert_trivia(self.leading_trivia)
        _assert_trivia(self.trailing_trivia)


@dataclass(slots=True)
class CstList:
    open_brace: Token  # OPEN_BRACE
    open_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    items: list[CstListItem] = field(default_factory=list[CstListItem])
    close_trivia: list[TriviaToken] = field(default_factory=list[TriviaToken])
    close_brace: Token | None = None  # CLOSE_BRACE

    def __post_init__(self) -> None:
        if self.open_brace.type != TokenType.OPEN_BRACE:
            raise TypeError("CstList.open_brace must be OPEN_BRACE")
        _assert_trivia(self.open_trivia)
        _assert_trivia(self.close_trivia)
        _assert_close_brace(self.close_brace)


# Type aliases (Python 3.12 `type` statements)
type CstBraceValue = CstList | CstBlock
type CstValue = CstScalar | CstComparison | CstTagged | CstList | CstBlock

__all__ = [
    "KEY_TOKENS",
    "SCALAR_TOKENS",
    "TAG_TOKENS",
    "CstBlock",
    "CstBraceValue",
    "CstComparison",
    "CstEntry",
    "CstList",
    "CstListItem",
    "CstScalar",
    "CstTagged",
    "CstValue",
    "TriviaToken",
]
