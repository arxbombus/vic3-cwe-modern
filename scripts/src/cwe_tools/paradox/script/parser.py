from __future__ import annotations

from dataclasses import dataclass

from cwe_tools.paradox.script.ast import (
    Assignment,
    Block,
    Comment,
    Scalar,
    Script,
    TaggedBlock,
    Value,
    ValueEntry,
)
from cwe_tools.paradox.script.lexer import LexError, Token, lex


class ParseError(ValueError):
    pass


@dataclass
class _Parser:
    tokens: list[Token]
    index: int = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def take(self, kind: str | None = None) -> Token:
        token = self.current
        if kind is not None and token.kind != kind:
            raise ParseError(
                f"Expected {kind}, got {token.kind} at {token.line}:{token.column}"
            )
        self.index += 1
        return token

    def parse_script(self) -> Script:
        entries = self.parse_entries(stop_at_rbrace=False)
        self.take("EOF")
        return Script(entries)

    def parse_entries(self, *, stop_at_rbrace: bool) -> list:
        entries = []
        while self.current.kind != "EOF":
            if self.current.kind == "RBRACE":
                if stop_at_rbrace:
                    break
                token = self.current
                raise ParseError(f"Stray closing brace at {token.line}:{token.column}")
            if self.current.kind == "COMMENT":
                entries.append(Comment(self.take().text))
                continue
            entries.append(self.parse_entry())
        return entries

    def parse_entry(self):
        if self.current.kind in {"ATOM", "STRING"} and self.peek().kind == "OP":
            key_token = self.take()
            operator = self.take("OP").text
            value = self.parse_value()
            return Assignment(key=key_token.text, value=value, operator=operator)
        return ValueEntry(self.parse_value())

    def parse_value(self) -> Value:
        if self.current.kind == "LBRACE":
            return self.parse_block()

        if self.current.kind not in {"ATOM", "STRING"}:
            token = self.current
            raise ParseError(f"Expected value at {token.line}:{token.column}")

        token = self.take()
        scalar = Scalar(token.text, quoted=token.kind == "STRING")
        if self.current.kind == "LBRACE" and not scalar.quoted:
            return TaggedBlock(tag=scalar.text, block=self.parse_block())
        return scalar

    def parse_block(self) -> Block:
        self.take("LBRACE")
        entries = self.parse_entries(stop_at_rbrace=True)
        if self.current.kind != "RBRACE":
            token = self.current
            raise ParseError(f"Unclosed block before {token.line}:{token.column}")
        self.take("RBRACE")
        return Block(entries)


def parse_script(text: str) -> Script:
    try:
        return _Parser(lex(text)).parse_script()
    except LexError as exc:
        raise ParseError(str(exc)) from exc
