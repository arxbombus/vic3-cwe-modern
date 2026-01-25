"""Modern Clausewitz lexer (lossless tokens + spans)."""

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
    TRIVIA = auto()
    EOF = auto()


@dataclass(slots=True)
class Token:
    type: TokenType
    value: str | int | float | bool | None
    raw: str
    line: int
    column: int
    start: int
    end: int


@dataclass(slots=True)
class LexerMetadata:
    keywords: set[str] = field(default_factory=set[str])
    modifiers: set[str] = field(default_factory=set[str])
    triggers: set[str] = field(default_factory=set[str])

    @classmethod
    def from_iterables(
        cls,
        *,
        keywords: Iterable[str] = (),
        modifiers: Iterable[str] = (),
        triggers: Iterable[str] = (),
    ) -> LexerMetadata:
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

            raise ValueError(f"Unexpected character '{char}' at {self._line}:{self._column}")

        # EOF
        self.tokens.append(Token(TokenType.EOF, None, "", self._line, self._column, self._pos, self._pos))
        return self.tokens

    # Emitters ----------------------------------------------------------------
    def _emit_whitespace(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        buffer: list[str] = []
        while not self._is_eof and self._peek().isspace():
            buffer.append(self._advance())
        raw = "".join(buffer)
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col, start, self._pos))

    def _emit_bom(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        raw = self._advance()
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col, start, self._pos))

    def _emit_comment(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        buffer: list[str] = []
        while not self._is_eof and self._peek() != "\n":
            buffer.append(self._advance())
        if not self._is_eof and self._peek() == "\n":
            buffer.append(self._advance())  # keep newline with comment
        raw = "".join(buffer)
        self.tokens.append(Token(TokenType.TRIVIA, raw, raw, start_line, start_col, start, self._pos))

    def _emit_brace(self, char: str) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        token_type = TokenType.OPEN_BRACE if char == "{" else TokenType.CLOSE_BRACE
        self._advance()
        self.tokens.append(Token(token_type, char, char, start_line, start_col, start, self._pos))

    def _emit_bracket_expression(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        buffer = [self._advance()]  # '['
        while not self._is_eof:
            ch = self._advance()
            buffer.append(ch)
            if ch == "]":
                raw = "".join(buffer)
                self.tokens.append(Token(TokenType.IDENTIFIER, raw, raw, start_line, start_col, start, self._pos))
                return
        raise ValueError(f"Unterminated bracket expression starting at {start_line}:{start_col}")

    def _emit_string(self) -> None:
        quote = self._peek()
        start_line, start_col, start = self._line, self._column, self._pos
        self._advance()  # consume quote
        raw_buffer: list[str] = [quote]
        val_buffer: list[str] = []
        while not self._is_eof:
            ch = self._peek()
            if ch == quote:
                raw_buffer.append(self._advance())
                value = "".join(val_buffer)
                raw = "".join(raw_buffer)
                self.tokens.append(Token(TokenType.STRING, value, raw, start_line, start_col, start, self._pos))
                return
            if ch == "\\":
                raw_buffer.append(self._advance())
                if not self._is_eof:
                    esc = self._advance()
                    raw_buffer.append(esc)
                    val_buffer.append(esc)
            else:
                raw_buffer.append(self._advance())
                val_buffer.append(ch)
        raise ValueError(f"Unterminated string starting at {start_line}:{start_col}")

    def _emit_number(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        buf = [self._advance()]  # first char (digit or '-')

        while not self._is_eof and (self._peek().isdigit() or self._peek() == "."):
            buf.append(self._advance())

        # If numbers are glued to identifier chars (e.g. 10k), treat as identifier-ish
        if not self._is_eof and (self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS):
            while not self._is_eof and (self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS):
                buf.append(self._advance())
            word = "".join(buf)
            token_type = self._classify(word)
            self.tokens.append(Token(token_type, word, word, start_line, start_col, start, self._pos))
            return

        text = "".join(buf)
        dot_count = text.count(".")

        # Clausewitz "dates" / version-ish tokens: 1836.1.1, 1.2.3, etc.
        # Treat as a STRING scalar token (no special date semantics).
        if dot_count >= 2:
            self.tokens.append(Token(TokenType.STRING, text, text, start_line, start_col, start, self._pos))
            return

        # Normal number
        value: int | float = float(text) if dot_count == 1 else int(text)
        self.tokens.append(Token(TokenType.NUMBER, value, text, start_line, start_col, start, self._pos))

    def _emit_operator(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        ch = self._advance()
        if not self._is_eof and self._peek() == "=" and ch in "<>!=":
            ch += self._advance()
        self.tokens.append(Token(TokenType.OPERATOR, ch, ch, start_line, start_col, start, self._pos))

    def _emit_identifier(self) -> None:
        start_line, start_col, start = self._line, self._column, self._pos
        buffer = [self._advance()]
        while not self._is_eof and (self._peek().isalnum() or self._peek() in IDENTIFIER_EXTRA_CHARS):
            buffer.append(self._advance())
        word = "".join(buffer)

        if word in {"yes", "no"}:
            self.tokens.append(Token(TokenType.BOOLEAN, word == "yes", word, start_line, start_col, start, self._pos))
            return

        token_type = self._classify(word)
        self.tokens.append(Token(token_type, word, word, start_line, start_col, start, self._pos))

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
        idx = self._pos + ahead
        if idx >= len(self.text):
            return "\0"
        return self.text[idx]

    def _advance(self) -> str:
        ch = self.text[self._pos]
        self._pos += 1
        if ch == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return ch


__all__ = ["ClausewitzLexer", "LexerMetadata", "Token", "TokenType"]
