"""Recursive-descent parser for Clausewitz tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from .document import ClausewitzDocument
from .nodes import ClausewitzBlock, ClausewitzComparison, ClausewitzList, ClausewitzScalar, ClausewitzValue
from .schema import DocumentSchema
from .lexer import ClausewitzLexer, LexerMetadata, Token, TokenType


@dataclass
class ParserConfig:
    metadata: LexerMetadata = field(default_factory=LexerMetadata)


class ClausewitzParser:
    def __init__(self, text: str, schema: DocumentSchema, config: ParserConfig | None = None):
        self.schema = schema
        self.config = config or ParserConfig()
        lexer = ClausewitzLexer(text, metadata=self.config.metadata)
        self.tokens = lexer.tokenize()
        self.index = 0

    def parse_document(self) -> ClausewitzDocument:
        root_block = self._parse_block_contents()
        return ClausewitzDocument(schema=self.schema, root=root_block)

    # Parsing helpers ---------------------------------------------------------
    def _parse_block_contents(self) -> ClausewitzBlock:
        block = ClausewitzBlock()
        while not self._current_is(TokenType.EOF) and not self._current_is(TokenType.CLOSE_BRACE):
            if self._current_is(TokenType.CLOSE_BRACE):
                break
            key = self._consume_key()
            if self._current_is(TokenType.OPERATOR) and self._current().value != "=":
                operator_token = self._advance()
                operator_value = operator_token.value
                if operator_value not in {">", "<", ">=", "<=", "!=", "="}:
                    raise TypeError("Operator tokens must contain string values")
                right = self._parse_scalar_value()
                block.add_entry(
                    key,
                    ClausewitzComparison(left=key, operator=cast(str, operator_value), right=right),
                )
                continue
            self._expect(TokenType.OPERATOR, "=")
            value = self._parse_value()
            block.add_entry(key, value)
        return block

    def _parse_value(self) -> ClausewitzValue:
        token = self._current()
        if token.type == TokenType.OPEN_BRACE:
            return self._parse_brace_value()
        if token.type in {TokenType.STRING, TokenType.NUMBER, TokenType.BOOLEAN}:
            return self._parse_scalar_value()
        if token.type in {TokenType.IDENTIFIER, TokenType.KEYWORD, TokenType.MODIFIER, TokenType.TRIGGER}:
            return self._parse_scalar_value()
        raise ValueError(f"Unexpected token {token.type} when parsing value")

    def _parse_brace_value(self) -> ClausewitzValue:
        self._expect(TokenType.OPEN_BRACE)
        if self._brace_is_object():
            block = self._parse_block_contents()
            self._expect(TokenType.CLOSE_BRACE)
            return block
        values = self._parse_list_values()
        self._expect(TokenType.CLOSE_BRACE)
        return ClausewitzList(values=values)

    def _parse_list_values(self) -> list[ClausewitzValue]:
        values: list[ClausewitzValue] = []
        while not self._current_is(TokenType.CLOSE_BRACE):
            if self._current_is(TokenType.OPEN_BRACE):
                values.append(self._parse_brace_value())
                continue
            if self._is_comparison_start():
                left = self._consume_key()
                operator_token = self._advance()
                operator_value = operator_token.value
                if operator_value not in {">", "<", ">=", "<=", "!=", "="}:
                    raise TypeError("Invalid comparison operator in list context")
                right = self._parse_scalar_value()
                values.append(
                    ClausewitzComparison(left=left, operator=cast(str, operator_value), right=right)
                )
                continue
            values.append(self._parse_scalar_value())
        return values

    def _parse_scalar_value(self) -> ClausewitzScalar:
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
            return f"string({value})"
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError("Scalar tokens must resolve to primitive values")
        return value

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
        if self.index + 1 >= len(self.tokens):
            return False
        next_token = self.tokens[self.index + 1]
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
        value = token.value
        if not isinstance(value, (str, int, float)):
            raise TypeError("Identifier tokens must carry string or numeric values")
        return value
