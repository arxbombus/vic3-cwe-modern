"""CST edit session for structural and value mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from clausewitz.core import (
    ClausewitzLexer,
    ClausewitzParser,
    CstBlock,
    CstEntry,
    CstList,
    CstListItem,
    ParserConfig,
)
from clausewitz.core.cst import CstTagged, CstValue
from clausewitz.core.lexer import Token, TokenType
from clausewitz.core.schema import DocumentSchema
from clausewitz.model import (
    AstValue,
    Block as AstBlock,
    Entry as AstEntry,
    ListValue,
    ScalarValue,
    TaggedValue,
    lower_root,
)


@dataclass(frozen=True, slots=True)
class AstEntryRef:
    entry: AstEntry
    ancestors: tuple[str, ...]


@dataclass(slots=True)
class CstEditSession:
    cst_root: CstBlock
    schema: DocumentSchema
    ast_root: AstBlock | None = None
    parser_config: ParserConfig | None = None
    default_indent: int = 4

    def replace_entry_value_ast(self, ref: AstEntryRef, new_raw: str) -> CstEntry:
        cst_entry = self._cst_entry_for_ast_ref(ref)
        self._replace_entry_value_cst(cst_entry, new_raw)
        self._replace_entry_value_ast(ref.entry, new_raw)
        return cst_entry

    def replace_entry_value_cst(self, entry: CstEntry, new_raw: str) -> None:
        self._replace_entry_value_cst(entry, new_raw)

    def insert_entry_end_of_block(self, block: CstBlock, entry_raw: str) -> CstEntry:
        entry = self._parse_entry(entry_raw)
        prefix = self._block_entry_prefix(block)
        entry.leading_trivia = [_trivia_token(prefix)]
        block.entries.append(entry)
        return entry

    def insert_entry_end_of_block_ast(self, ref: AstEntryRef, entry_raw: str) -> CstEntry:
        cst_entry = self._cst_entry_for_ast_ref(ref)
        if cst_entry.value is None:
            raise ValueError("CST entry has no value")
        cst_block = _unwrap_block_cst(cst_entry.value)
        if cst_block is None:
            raise ValueError("CST entry value is not a block")
        new_cst_entry = self.insert_entry_end_of_block(cst_block, entry_raw)

        if self.ast_root is None:
            return new_cst_entry
        ast_block = _unwrap_block_ast(ref.entry.value)
        if ast_block is None:
            raise ValueError("AST entry value is not a block")
        new_ast_entry = _lower_entry_from_cst(new_cst_entry)
        ast_block.entries.append(new_ast_entry)
        return new_cst_entry

    def insert_item_end_of_list(self, lst: CstList, item_raw: str) -> CstListItem:
        item = self._parse_list_item(item_raw)
        prefix = self._list_item_prefix(lst)
        item.leading_trivia = [_trivia_token(prefix)]
        lst.items.append(item)
        return item

    def delete_entry(self, block: CstBlock, entry: CstEntry) -> None:
        block.entries.remove(entry)

    def delete_entry_ast(self, ref: AstEntryRef) -> None:
        if self.ast_root is None:
            raise ValueError("AST root is required for AST-based edits")
        ast_block = self.ast_root
        cst_block = self.cst_root
        for seg in ref.ancestors:
            ast_block, cst_block = _descend_block_pair(ast_block, cst_block, seg, ref.entry)
        idx = ast_block.entries.index(ref.entry)
        del ast_block.entries[idx]
        del cst_block.entries[idx]

    def cst_block_for_ast_ref(self, ref: AstEntryRef) -> CstBlock | None:
        cst_entry = self._cst_entry_for_ast_ref(ref)
        if cst_entry.value is None:
            return None
        return _unwrap_block_cst(cst_entry.value)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _replace_entry_value_ast(self, entry: AstEntry, new_raw: str) -> None:
        if isinstance(entry.value, ScalarValue):
            parsed = _parse_scalar_raw(new_raw)
            entry.value.value = parsed.value
            entry.value.raw = parsed.raw

    def _replace_entry_value_cst(self, entry: CstEntry, new_raw: str) -> None:
        if entry.key is None or entry.operator is None:
            raise ValueError("CST entry missing key or operator")
        parsed_entry = self._parse_entry(f"{entry.key.raw} {entry.operator.raw} {new_raw}")
        entry.value = parsed_entry.value

    def _parse_entry(self, text: str) -> CstEntry:
        parser = ClausewitzParser(text=text, schema=self.schema, config=self.parser_config)
        root = parser.parse_document()
        if not root.entries:
            raise ValueError("Parsed entry is empty")
        return root.entries[0]

    def _parse_list_item(self, raw: str) -> CstListItem:
        entry = self._parse_entry(f"__x__ = {{ {raw} }}")
        if not isinstance(entry.value, CstList) or not entry.value.items:
            raise ValueError("Parsed list item is empty")
        return entry.value.items[0]

    def _block_entry_prefix(self, block: CstBlock) -> str:
        prefix = _infer_prefix_from_trivia(_iter_block_trivia(block), default_indent=self.default_indent)
        return prefix or ("\n" + (" " * self.default_indent))

    def _list_item_prefix(self, lst: CstList) -> str:
        prefix = _infer_prefix_from_trivia(_iter_list_trivia(lst), default_indent=self.default_indent)
        if prefix:
            return prefix
        return " "

    def _cst_entry_for_ast_ref(self, ref: AstEntryRef) -> CstEntry:
        if self.ast_root is None:
            raise ValueError("AST root is required for AST-based edits")
        ast_block = self.ast_root
        cst_block = self.cst_root
        for seg in ref.ancestors:
            ast_block, cst_block = _descend_block_pair(ast_block, cst_block, seg, ref.entry)
        idx = ast_block.entries.index(ref.entry)
        return cst_block.entries[idx]


def _descend_block_pair(
    ast_block: AstBlock, cst_block: CstBlock, key: str, target_entry: AstEntry
) -> tuple[AstBlock, CstBlock]:
    ast_candidates: list[AstEntry] = []
    for entry in ast_block.entries:
        if entry.key != key:
            continue
        child = _unwrap_block_ast(entry.value)
        if child is None:
            continue
        ast_candidates.append(entry)

    if not ast_candidates:
        raise ValueError(f"AST block path not found: {key}")

    ast_index = None
    ast_child: AstBlock | None = None
    for i, entry in enumerate(ast_candidates):
        child = _unwrap_block_ast(entry.value)
        if child is not None and _block_contains_entry_ast(child, target_entry):
            ast_index = i
            ast_child = child
            break

    if ast_index is None:
        raise ValueError(f"AST block path not found for entry: {key}")

    cst_candidates: list[CstEntry] = []
    for entry in cst_block.entries:
        if entry.key is None or entry.value is None:
            continue
        if entry.key.raw != key:
            continue
        child = _unwrap_block_cst(entry.value)
        if child is None:
            continue
        cst_candidates.append(entry)

    if ast_index >= len(cst_candidates):
        raise ValueError(f"CST block path mismatch for key: {key}")

    _val = cst_candidates[ast_index].value
    if _val is None:
        raise ValueError(f"CST entry value missing for key: {key}")
    cst_child = _unwrap_block_cst(_val)

    if ast_child is None:
        raise ValueError(f"AST block path not found for entry: {key}")
    if cst_child is None:
        raise ValueError(f"CST block path not found for entry: {key}")

    return ast_child, cst_child


def _unwrap_block_ast(value: AstValue) -> AstBlock | None:
    if isinstance(value, AstBlock):
        return value
    if isinstance(value, TaggedValue) and isinstance(value.value, AstBlock):
        return value.value
    return None


def _block_contains_entry_ast(block: AstBlock, target: AstEntry) -> bool:
    for entry in block.entries:
        if entry is target:
            return True
        child = _unwrap_block_ast(entry.value)
        if child is not None and _block_contains_entry_ast(child, target):
            return True
        child_blocks = _unwrap_list_blocks_ast(entry.value)
        for sub in child_blocks:
            if _block_contains_entry_ast(sub, target):
                return True
    return False


def _unwrap_list_blocks_ast(value: AstValue) -> list[AstBlock]:
    if isinstance(value, ListValue):
        return [v for v in value.items if isinstance(v, AstBlock)]
    if isinstance(value, TaggedValue) and isinstance(value.value, ListValue):
        return [v for v in value.value.items if isinstance(v, AstBlock)]
    return []


def _unwrap_block_cst(value: CstValue) -> CstBlock | None:
    if isinstance(value, CstBlock):
        return value
    if isinstance(value, CstTagged) and isinstance(value.value, CstBlock):
        return value.value
    return None


def _iter_block_trivia(block: CstBlock) -> Iterable[Token]:
    if block.entries:
        for t in block.entries[-1].leading_trivia:
            yield t
    else:
        for t in block.open_trivia:
            yield t


def _iter_list_trivia(lst: CstList) -> Iterable[Token]:
    if lst.items:
        for t in lst.items[-1].leading_trivia:
            yield t
    else:
        for t in lst.open_trivia:
            yield t


def _infer_prefix_from_trivia(trivia: Iterable[Token], *, default_indent: int) -> str:
    for t in trivia:
        raw = t.raw
        if "\n" in raw:
            return raw[raw.rfind("\n") :]
    return "\n" + (" " * default_indent)


def _trivia_token(raw: str) -> Token:
    return Token(TokenType.TRIVIA, raw, raw, 0, 0, 0, 0)


def _parse_scalar_raw(raw: str) -> ScalarValue:
    text = raw.strip()
    if not text:
        raise ValueError("Scalar raw text is empty")

    lexer = ClausewitzLexer(text)
    tokens = lexer.tokenize()
    non_trivia = [t for t in tokens if t.type not in {TokenType.TRIVIA, TokenType.EOF}]
    if len(non_trivia) != 1:
        raise ValueError("Expected a single scalar token")
    tok = non_trivia[0]
    if tok.value is None:
        raise ValueError("Scalar token has no value")
    return ScalarValue(value=tok.value, raw=tok.raw, origin=None)


def _lower_entry_from_cst(entry: CstEntry) -> AstEntry:
    temp = CstBlock(entries=[entry])
    block = lower_root(temp)
    if not block.entries:
        raise ValueError("Lowered entry is empty")
    return block.entries[0]


__all__ = ["CstEditSession"]
