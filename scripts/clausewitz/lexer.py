"""Modern Clausewitz lexer for v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterable

IDENTIFIER_EXTRA_CHARS = {"_", ".", "@", ":", "-", "^", "?", "|"}


class TokenType(Enum):
    IDENTIFIER = auto()
    KEYWORD = auto()
    MODIFIER = auto()
    TRIGGER = auto()
    OPEN_BRACE = auto()
    CLOSE_BRACE = auto()
    STRING = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    OPERATOR = auto()
    COMMENT = auto()
    TRIVIA = auto()
    EOF = auto()


@dataclass(slots=True)
class Token:
    type: TokenType
    value: str | int | float | bool | None
    raw: str
    line: int
    column: int


@dataclass(slots=True)
class LexerMetadata:
    keywords: set[str] = field(default_factory=set)
    modifiers: set[str] = field(default_factory=set)
    triggers: set[str] = field(default_factory=set)

    @classmethod
    def from_iterables(
        cls,
        *,
        keywords: Iterable[str] = (),
        modifiers: Iterable[str] = (),
        triggers: Iterable[str] = (),
    ):
        return cls(set(keywords), set(modifiers), set(triggers))


class ClausewitzLexer:
    def __init__(self, text: str, metadata: LexerMetadata | None = None):
        self.text = text
        self.metadata = metadata or LexerMetadata()
        self.tokens: list[Token] = []
        self._pos = 0
        self._line = 1
        self._column = 1

    def tokenize(self) -> list[Token]:
        while not self._is_eof:
            char = self._peek()
            if char == "\ufeff":
                self._emit_bom()
                continue
            if char.isspace():
                self._emit_whitespace()
                continue
            if char == "#":
                self._emit_comment()
                continue
            if char in "{}":
                self._emit_brace(char)
                continue
            if char == "[":
                self._emit_bracket_expression()
                continue
            if char in ('"', "'"):
                self._emit_string()
                continue
            if char.isdigit() or (char == "-" and self._peek(1).isdigit()):
                self._emit_number()
                continue
            if char in "<>!=":
                self._emit_operator()
                continue
            if char.isalpha() or char in IDENTIFIER_EXTRA_CHARS:
                self._emit_identifier()
                continue
            raise ValueError(
                f"Unexpected character '{char}' at {self._line}:{self._column}"
            )

        self.tokens.append(Token(TokenType.EOF, None, "", self._line, self._column))
        return self.tokens

    def _emit_whitespace(self) -> None:
        start_line, start_col = self._line, self._column
        buffer: list[str] = []
        while not self._is_eof and self._peek().isspace():
            buffer.append(self._advance())
        raw = "".join(buffer)
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col))

    def _emit_bom(self) -> None:
        start_line, start_col = self._line, self._column
        raw = self._advance()
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col))

    def _emit_comment(self) -> None:
        start_line, start_col = self._line, self._column
        buffer: list[str] = []
        while not self._is_eof and self._peek() != "\n":
            buffer.append(self._advance())
        if not self._is_eof and self._peek() == "\n":
            buffer.append(self._advance())
        raw = "".join(buffer)
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col))

    def _emit_brace(self, char: str) -> None:
        token_type = TokenType.OPEN_BRACE if char == "{" else TokenType.CLOSE_BRACE
        self.tokens.append(Token(token_type, char, char, self._line, self._column))
        self._advance()

    def _emit_bracket_expression(self) -> None:
        start_line, start_col = self._line, self._column
        buffer = [self._advance()]  # consume '['
        while not self._is_eof:
            char = self._advance()
            buffer.append(char)
            if char == "]":
                word = "".join(buffer)
                self.tokens.append(
                    Token(TokenType.IDENTIFIER, word, word, start_line, start_col)
                )
                return
        raise ValueError(
            f"Unterminated bracket expression starting at {start_line}:{start_col}"
        )

    def _emit_string(self) -> None:
        quote = self._peek()
        start_line, start_col = self._line, self._column
        self._advance()
        raw_buffer: list[str] = [quote]
        value_buffer: list[str] = []
        while not self._is_eof:
            char = self._peek()
            if char == quote:
                raw_buffer.append(self._advance())
                value = "".join(value_buffer)
                raw = "".join(raw_buffer)
                self.tokens.append(
                    Token(TokenType.STRING, value, raw, start_line, start_col)
                )
                return
            if char == "\\":
                raw_buffer.append(self._advance())
                if not self._is_eof:
                    escaped = self._advance()
                    raw_buffer.append(escaped)
                    value_buffer.append(escaped)
            else:
                raw_buffer.append(self._advance())
                value_buffer.append(char)
        raise ValueError(f"Unterminated string starting at {start_line}:{start_col}")

    def _emit_number(self) -> None:
        start_line, start_col = self._line, self._column
        buffer = [self._advance()]  # consume first char
        while not self._is_eof and (self._peek().isdigit() or self._peek() == "."):
            buffer.append(self._advance())
        if not self._is_eof and (
            self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS
        ):
            while not self._is_eof and (
                self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS
            ):
                buffer.append(self._advance())
            word = "".join(buffer)
            token_type = self._classify(word)
            self.tokens.append(Token(token_type, word, word, start_line, start_col))
            return
        text = "".join(buffer)
        dot_count = text.count(".")
        if dot_count > 1:
            self.tokens.append(
                Token(TokenType.STRING, text, text, start_line, start_col)
            )
            return
        value: int | float
        value = float(text) if dot_count == 1 else int(text)
        self.tokens.append(Token(TokenType.NUMBER, value, text, start_line, start_col))

    def _emit_operator(self) -> None:
        start_line, start_col = self._line, self._column
        char = self._advance()
        if not self._is_eof and self._peek() == "=" and char in "<>!=":
            char += self._advance()
        self.tokens.append(Token(TokenType.OPERATOR, char, char, start_line, start_col))

    def _emit_identifier(self) -> None:
        start_line, start_col = self._line, self._column
        buffer = [self._advance()]
        while not self._is_eof and (
            self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS
        ):
            buffer.append(self._advance())
        word = "".join(buffer)
        if word in {"yes", "no"}:
            value = word == "yes"
            self.tokens.append(
                Token(TokenType.BOOLEAN, value, word, start_line, start_col)
            )
            return
        token_type = self._classify(word)
        self.tokens.append(Token(token_type, word, word, start_line, start_col))

    # Helpers -----------------------------------------------------------------
    def _classify(self, word: str) -> TokenType:
        if word in self.metadata.keywords:
            return TokenType.KEYWORD
        if word in self.metadata.modifiers:
            return TokenType.MODIFIER
        if word in self.metadata.triggers:
            return TokenType.TRIGGER
        return TokenType.IDENTIFIER

    @property
    def _is_eof(self) -> bool:
        return self._pos >= len(self.text)

    def _peek(self, ahead: int = 0) -> str:
        index = self._pos + ahead
        if index >= len(self.text):
            return "\0"
        return self.text[index]

    def _advance(self) -> str:
        char = self.text[self._pos]
        self._pos += 1
        if char == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return char


__all__ = ["ClausewitzLexer", "LexerMetadata", "Token", "TokenType"]
