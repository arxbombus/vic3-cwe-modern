"""Recursive-descent parser for Clausewitz tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from .document import ClausewitzDocument
from .nodes import (
    ClausewitzBlock,
    ClausewitzComparison,
    ClausewitzList,
    ClausewitzListItem,
    ClausewitzScalarValue,
    ClausewitzValue,
)
from .schema import DocumentSchema
from .lexer import ClausewitzLexer, LexerMetadata, Token, TokenType


@dataclass
class ParserConfig:
    metadata: LexerMetadata = field(default_factory=LexerMetadata)


class ClausewitzParser:
    def __init__(
        self, text: str, schema: DocumentSchema, config: ParserConfig | None = None
    ):
        self.schema = schema
        self.config = config or ParserConfig()
        lexer = ClausewitzLexer(text, metadata=self.config.metadata)
        self.tokens = lexer.tokenize()
        self.index = 0

    def parse_document(self) -> ClausewitzDocument:
        leading_trivia = self._collect_trivia()
        root_block = self._parse_block_contents(leading_trivia=leading_trivia)
        return ClausewitzDocument(schema=self.schema, root=root_block)

    # Parsing helpers ---------------------------------------------------------
    def _parse_block_contents(self, *, leading_trivia: str = "") -> ClausewitzBlock:
        block = ClausewitzBlock(leading_trivia=leading_trivia)
        while True:
            entry_leading_trivia = self._collect_trivia()
            if self._current_is(TokenType.EOF) or self._current_is(
                TokenType.CLOSE_BRACE
            ):
                block.trailing_trivia = entry_leading_trivia
                break
            key = self._consume_key()
            key_trivia = self._collect_trivia()
            if self._current_is(TokenType.OPERATOR) and self._current().value != "=":
                operator_token = self._advance()
                operator_value = operator_token.value
                if operator_value not in {">", "<", ">=", "<=", "!=", "="}:
                    raise TypeError("Operator tokens must contain string values")
                operator_trivia = self._collect_trivia()
                right = self._parse_scalar_value()
                trailing_trivia = self._collect_trivia()
                block.add_entry(
                    key,
                    ClausewitzComparison(
                        left=key, operator=cast(str, operator_value), right=right
                    ),
                    operator=cast(str, operator_value),
                    leading_trivia=entry_leading_trivia,
                    key_trivia=key_trivia,
                    operator_trivia=operator_trivia,
                    trailing_trivia=trailing_trivia,
                )
                continue
            self._expect(TokenType.OPERATOR, "=")
            operator_trivia = self._collect_trivia()
            value = self._parse_value()
            trailing_trivia = self._collect_trivia()
            block.add_entry(
                key,
                value,
                operator="=",
                leading_trivia=entry_leading_trivia,
                key_trivia=key_trivia,
                operator_trivia=operator_trivia,
                trailing_trivia=trailing_trivia,
            )
        return block

    def _parse_value(self) -> ClausewitzValue:
        token = self._current()
        if token.type == TokenType.OPEN_BRACE:
            return self._parse_brace_value()
        if token.type in {TokenType.STRING, TokenType.NUMBER, TokenType.BOOLEAN}:
            return self._parse_scalar_value()
        if token.type in {
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.MODIFIER,
            TokenType.TRIGGER,
        }:
            return self._parse_scalar_value()
        raise ValueError(f"Unexpected token {token.type} when parsing value")

    def _parse_brace_value(self) -> ClausewitzValue:
        self._expect(TokenType.OPEN_BRACE)
        open_trivia = self._collect_trivia()
        if self._brace_is_object():
            block = self._parse_block_contents(leading_trivia=open_trivia)
            self._expect(TokenType.CLOSE_BRACE)
            return block
        items, close_trivia = self._parse_list_values()
        self._expect(TokenType.CLOSE_BRACE)
        return ClausewitzList(
            items=items, open_trivia=open_trivia, close_trivia=close_trivia
        )

    def _parse_list_values(self) -> tuple[list[ClausewitzListItem], str]:
        items: list[ClausewitzListItem] = []
        while True:
            leading_trivia = self._collect_trivia()
            if self._current_is(TokenType.CLOSE_BRACE):
                return items, leading_trivia
            if self._current_is(TokenType.OPEN_BRACE):
                value = self._parse_brace_value()
                trailing_trivia = self._collect_trivia()
                items.append(
                    ClausewitzListItem(
                        value=value,
                        leading_trivia=leading_trivia,
                        trailing_trivia=trailing_trivia,
                    )
                )
                continue
            if self._is_comparison_start():
                left = self._consume_key()
                key_trivia = self._collect_trivia()
                operator_token = self._advance()
                operator_value = operator_token.value
                if operator_value not in {">", "<", ">=", "<=", "!=", "="}:
                    raise TypeError("Invalid comparison operator in list context")
                operator_trivia = self._collect_trivia()
                right = self._parse_scalar_value()
                trailing_trivia = self._collect_trivia()
                items.append(
                    ClausewitzListItem(
                        value=ClausewitzComparison(
                            left=left, operator=cast(str, operator_value), right=right
                        ),
                        leading_trivia=leading_trivia,
                        key_trivia=key_trivia,
                        operator_trivia=operator_trivia,
                        trailing_trivia=trailing_trivia,
                    )
                )
                continue
            value = self._parse_scalar_value()
            trailing_trivia = self._collect_trivia()
            items.append(
                ClausewitzListItem(
                    value=value,
                    leading_trivia=leading_trivia,
                    trailing_trivia=trailing_trivia,
                )
            )

    def _parse_scalar_value(self) -> ClausewitzScalarValue:
        token = self._current()
        if token.type not in (
            TokenType.STRING,
            TokenType.NUMBER,
            TokenType.BOOLEAN,
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.MODIFIER,
            TokenType.TRIGGER,
        ):
            raise ValueError(f"Expected scalar value, got {token.type}")
        self._advance()
        value = token.value
        if token.type == TokenType.STRING:
            if not isinstance(value, str):
                raise TypeError("String tokens must provide string values")
            return ClausewitzScalarValue(value=value, raw=token.raw)
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError("Scalar tokens must resolve to primitive values")
        return ClausewitzScalarValue(value=value, raw=token.raw)

    def _brace_is_object(self) -> bool:
        depth = 1
        idx = self.index
        while idx < len(self.tokens):
            token = self.tokens[idx]
            if token.type == TokenType.OPEN_BRACE:
                depth += 1
            elif token.type == TokenType.CLOSE_BRACE:
                depth -= 1
                if depth == 0:
                    return False
            elif depth == 1 and token.type == TokenType.OPERATOR and token.value == "=":
                return True
            idx += 1
        return False

    def _is_comparison_start(self) -> bool:
        token = self._current()
        if token.type not in {
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.MODIFIER,
            TokenType.TRIGGER,
        }:
            return False
        next_token = self._peek_non_trivia(self.index + 1)
        if next_token is None:
            return False
        return next_token.type == TokenType.OPERATOR and next_token.value != "="

    # Token utilities --------------------------------------------------------
    def _current(self) -> Token:
        return self.tokens[self.index]

    def _current_is(self, type_: TokenType) -> bool:
        return self._current().type == type_

    def _advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _expect(self, type_: TokenType, value: str | None = None) -> Token:
        token = self._current()
        if token.type != type_:
            raise ValueError(f"Expected token {type_}, got {token.type}")
        if value is not None and token.value != value:
            raise ValueError(f"Expected token value {value}, got {token.value}")
        self.index += 1
        return token

    def _consume_key(self) -> str:
        token = self._current()
        if token.type not in {
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.MODIFIER,
            TokenType.TRIGGER,
            TokenType.NUMBER,
        }:
            raise ValueError(f"Expected identifier, got {token.type}")
        self.index += 1
        return token.raw

    def _collect_trivia(self) -> str:
        chunks: list[str] = []
        while self._current_is(TokenType.TRIVIA):
            token = self._advance()
            if isinstance(token.value, str):
                chunks.append(token.value)
        return "".join(chunks)

    def _peek_non_trivia(self, start_index: int) -> Token | None:
        idx = start_index
        while idx < len(self.tokens) and self.tokens[idx].type == TokenType.TRIVIA:
            idx += 1
        if idx >= len(self.tokens):
            return None
        return self.tokens[idx]
