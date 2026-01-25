"""Recursive-descent parser that produces a lossless CST (supports tagged brace values)."""

from __future__ import annotations

from dataclasses import dataclass, field

from clausewitz.core.cst import (
    KEY_TOKENS,
    TAG_TOKENS,
    CstBlock,
    CstBraceValue,
    CstComparison,
    CstEntry,
    CstList,
    CstListItem,
    CstScalar,
    CstTagged,
    CstValue,
    TriviaToken,
)
from clausewitz.core.lexer import (
    ClausewitzLexer,
    LexerMetadata,
    Token,
    TokenType,
)
from clausewitz.core.schema import DocumentSchema


@dataclass
class ParserConfig:
    metadata: LexerMetadata = field(default_factory=LexerMetadata)


class ClausewitzParser:
    def __init__(self, text: str, schema: DocumentSchema, config: ParserConfig | None = None):
        self.schema = schema
        self.config = config or ParserConfig()
        self.tokens = ClausewitzLexer(text, metadata=self.config.metadata).tokenize()
        self.index = 0

    # --------------------------------------------------------------------- #
    # Entry point
    # --------------------------------------------------------------------- #
    def parse_document(self) -> CstBlock:
        """
        Parse an unbraced root "block" until EOF.
        Clausewitz script files are typically a sequence of entries at top-level.
        """
        leading = self._collect_trivia()
        root = CstBlock(leading_trivia=leading, open_brace=None)

        while True:
            entry_leading = self._collect_trivia()
            if self._current_is(TokenType.EOF):
                root.close_trivia = entry_leading
                root.close_brace = None
                break
            root.entries.append(self._parse_entry(entry_leading))

        return root

    # --------------------------------------------------------------------- #
    # Entry parsing
    # --------------------------------------------------------------------- #
    def _parse_entry(self, entry_leading: list[TriviaToken]) -> CstEntry:
        entry = CstEntry(leading_trivia=entry_leading)

        entry.key = self._consume_key_token()
        entry.between_key_op_trivia = self._collect_trivia()

        entry.operator = self._expect(TokenType.OPERATOR)
        entry.between_op_value_trivia = self._collect_trivia()

        entry.value = self._parse_value()

        entry.trailing_trivia = self._collect_trivia()
        return entry

    # --------------------------------------------------------------------- #
    # Value parsing
    # --------------------------------------------------------------------- #
    def _parse_value(self) -> CstValue:
        tok = self._current()

        if tok.type == TokenType.OPEN_BRACE:
            return self._parse_brace_value()

        # tagged brace value: <tag> { ... }
        if self._is_tagged_brace_value_start():
            tag = self._advance()
            between = self._collect_trivia()
            brace_value = self._parse_brace_value()
            return CstTagged(tag=tag, between_tag_value_trivia=between, value=brace_value)

        return self._parse_scalar()

    def _parse_brace_value(self) -> CstBraceValue:
        open_brace = self._expect(TokenType.OPEN_BRACE)
        open_trivia = self._collect_trivia()

        # Decide object vs list by scanning for '=' at depth 1 within braces.
        if self._brace_is_object():
            block = CstBlock(open_brace=open_brace, open_trivia=open_trivia)
            while True:
                entry_leading = self._collect_trivia()
                if self._current_is(TokenType.CLOSE_BRACE):
                    block.close_trivia = entry_leading
                    block.close_brace = self._expect(TokenType.CLOSE_BRACE)
                    return block
                block.entries.append(self._parse_entry(entry_leading))

        # Otherwise, list.
        items: list[CstListItem] = []
        while True:
            item_leading = self._collect_trivia()
            if self._current_is(TokenType.CLOSE_BRACE):
                close_trivia = item_leading
                close_brace = self._expect(TokenType.CLOSE_BRACE)
                return CstList(
                    open_brace=open_brace,
                    open_trivia=open_trivia,
                    items=items,
                    close_trivia=close_trivia,
                    close_brace=close_brace,
                )

            # Nested brace-value (block/list)
            if self._current_is(TokenType.OPEN_BRACE):
                v = self._parse_brace_value()
                trailing = self._collect_trivia()
                items.append(CstListItem(leading_trivia=item_leading, value=v, trailing_trivia=trailing))
                continue

            # List-context comparison: <key> <op != '='> <scalar>
            if self._is_list_comparison_start():
                comp = self._parse_list_comparison()
                trailing = self._collect_trivia()
                items.append(CstListItem(leading_trivia=item_leading, value=comp, trailing_trivia=trailing))
                continue

            # List item can be tagged brace too: rgb { 255 0 0 }
            if self._is_tagged_brace_value_start():
                tag_tok = self._advance()
                between = self._collect_trivia()
                brace_value = self._parse_brace_value()
                tagged = CstTagged(tag=tag_tok, between_tag_value_trivia=between, value=brace_value)
                trailing = self._collect_trivia()
                items.append(CstListItem(leading_trivia=item_leading, value=tagged, trailing_trivia=trailing))
                continue

            v = self._parse_scalar()
            trailing = self._collect_trivia()
            items.append(CstListItem(leading_trivia=item_leading, value=v, trailing_trivia=trailing))

    def _parse_scalar(self) -> CstScalar:
        tok = self._current()
        if tok.type not in {
            TokenType.STRING,
            TokenType.NUMBER,
            TokenType.BOOLEAN,
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.MODIFIER,
            TokenType.TRIGGER,
        }:
            raise ValueError(f"Expected scalar, got {tok.type}")
        self._advance()
        return CstScalar(token=tok)

    # --------------------------------------------------------------------- #
    # Lookaheads / classification
    # --------------------------------------------------------------------- #
    def _is_tagged_brace_value_start(self) -> bool:
        """
        Detect: <tag_token> (trivia) '{'
        Used for patterns like: rgb { 255 0 0 }.
        """
        tok = self._current()
        if tok.type not in TAG_TOKENS:
            return False
        nxt = self._peek_non_trivia(self.index + 1)
        return nxt is not None and nxt.type == TokenType.OPEN_BRACE

    def _brace_is_object(self) -> bool:
        """
        We have just consumed an OPEN_BRACE and are positioned after it.
        Scan forward until the matching CLOSE_BRACE.
        If we see '=' at depth==1, treat as an object/block; else list.
        """
        depth = 1
        idx = self.index
        while idx < len(self.tokens):
            t = self.tokens[idx]
            if t.type == TokenType.OPEN_BRACE:
                depth += 1
            elif t.type == TokenType.CLOSE_BRACE:
                depth -= 1
                if depth == 0:
                    return False
            elif depth == 1 and t.type == TokenType.OPERATOR and t.value == "=":
                return True
            idx += 1
        return False

    def _is_list_comparison_start(self) -> bool:
        """Detect: <key_token> (trivia) <op_token where op != '='>."""
        tok = self._current()
        if tok.type not in KEY_TOKENS:
            return False
        nxt = self._peek_non_trivia(self.index + 1)
        return nxt is not None and nxt.type == TokenType.OPERATOR and nxt.value != "="

    # --------------------------------------------------------------------- #
    # List comparison parsing
    # --------------------------------------------------------------------- #
    def _parse_list_comparison(self) -> CstComparison:
        left = self._consume_key_token()
        between_left_op = self._collect_trivia()

        op = self._expect(TokenType.OPERATOR)
        if op.value == "=":
            raise ValueError("List comparison operator must not be '='")

        between_op_right = self._collect_trivia()
        right = self._parse_scalar()
        return CstComparison(
            left=left,
            between_left_op_trivia=between_left_op,
            operator=op,
            between_op_right_trivia=between_op_right,
            right=right,
        )

    # --------------------------------------------------------------------- #
    # Token utilities
    # --------------------------------------------------------------------- #
    def _current(self) -> Token:
        return self.tokens[self.index]

    def _current_is(self, ty: TokenType) -> bool:
        return self._current().type == ty

    def _advance(self) -> Token:
        prev = self.tokens[self.index]
        self.index += 1
        return prev

    def _expect(self, ty: TokenType, value: str | None = None) -> Token:
        tok = self._current()
        if tok.type != ty:
            raise ValueError(f"Expected token {ty}, got {tok.type}")
        if value is not None and tok.value != value:
            raise ValueError(f"Expected token value {value}, got {tok.value}")
        self.index += 1
        return tok

    def _consume_key_token(self) -> Token:
        tok = self._current()
        if tok.type not in KEY_TOKENS:
            raise ValueError(f"Expected key token, got {tok.type}")
        self.index += 1
        return tok

    def _collect_trivia(self) -> list[TriviaToken]:
        out: list[TriviaToken] = []
        while self._current_is(TokenType.TRIVIA):
            out.append(self._advance())
        return out

    def _peek_non_trivia(self, start_index: int) -> Token | None:
        idx = start_index
        while idx < len(self.tokens) and self.tokens[idx].type == TokenType.TRIVIA:
            idx += 1
        if idx >= len(self.tokens):
            return None
        return self.tokens[idx]


__all__ = ["ClausewitzParser", "ParserConfig"]
