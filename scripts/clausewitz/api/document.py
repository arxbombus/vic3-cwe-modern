"""High-level Clausewitz document wrapper (parse -> CST/AST -> edits -> save)."""

from dataclasses import dataclass, replace
from pathlib import Path

from clausewitz.core import (
    ClausewitzParser,
    CstBlock,
    DocumentSchema,
    ParserConfig,
)
from clausewitz.edit import CstEditSession
from clausewitz.format import print_cst
from clausewitz.io import SaveMode, SaveOptions, save_document
from clausewitz.model import Block, Entry, Operator, lower_root
from clausewitz.query import (
    delete_entries,
    insert_entries_end_of_blocks,
    replace_values,
    scale_numeric_values,
)


@dataclass(slots=True)
class ClausewitzDocument:
    schema: DocumentSchema
    original_text: str
    cst_root: CstBlock | None = None
    ast_root: Block | None = None
    edit_session: CstEditSession | None = None
    parser_config: ParserConfig | None = None

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        schema: DocumentSchema,
        parser_config: ParserConfig | None = None,
    ) -> "ClausewitzDocument":
        parser = ClausewitzParser(text=text, schema=schema, config=parser_config)
        cst = parser.parse_document()
        ast = lower_root(cst)
        return cls(
            schema=schema,
            original_text=text,
            cst_root=cst,
            ast_root=ast,
            edit_session=None,
            parser_config=parser_config,
        )

    @property
    def root(self) -> Block:
        """
        Convenience accessor: prefer AST root when available.
        This keeps most callers simple.
        """
        if self.ast_root is None:
            raise ValueError("Document has no AST root. Lower CST to AST first.")
        return self.ast_root

    def entries(self) -> list[Entry]:
        return self.root.entries

    @property
    def session(self) -> CstEditSession:
        if self.edit_session is None:
            if self.cst_root is None:
                raise ValueError("Document has no CST root")
            self.edit_session = CstEditSession(
                cst_root=self.cst_root, schema=self.schema, ast_root=self.ast_root, parser_config=self.parser_config
            )
        return self.edit_session

    def apply(self) -> str:
        if self.cst_root is None:
            raise ValueError("Document has no CST root")
        return print_cst(self.cst_root)

    def delete_entries(
        self,
        *,
        key_pattern: str,
        ancestor_suffix_pattern: str = "",
        exclude_key_patterns: tuple[str, ...] = (),
    ) -> None:
        delete_entries(
            self.root,
            key_pattern=key_pattern,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns,
            session=self.session,
        )

    def replace_values(
        self,
        *,
        key_pattern: str,
        new_raw: str,
        ancestor_suffix_pattern: str = "",
        exclude_key_patterns: tuple[str, ...] = (),
        operator: Operator | None = None,
    ) -> None:
        replace_values(
            self.root,
            key_pattern=key_pattern,
            new_raw=new_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns,
            operator=operator,
            session=self.session,
        )

    def scale_numeric_values(
        self,
        *,
        key_pattern: str,
        factor: float,
        ancestor_suffix_pattern: str = "",
        exclude_key_patterns: tuple[str, ...] = (),
        operator: Operator = "=",
    ) -> None:
        scale_numeric_values(
            self.root,
            key_pattern=key_pattern,
            factor=factor,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns,
            operator=operator,
            session=self.session,
        )

    def insert_entries_end_of_blocks(
        self,
        *,
        key_pattern: str,
        entry_raw: str,
        ancestor_suffix_pattern: str = "",
        exclude_key_patterns: tuple[str, ...] = (),
    ) -> None:
        insert_entries_end_of_blocks(
            self.root,
            key_pattern=key_pattern,
            entry_raw=entry_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns,
            session=self.session,
        )

    def save(
        self,
        path: str | Path,
        *,
        mode: SaveMode = "preserve",
        options: SaveOptions | None = None,
    ) -> str:
        if options is None:
            opts = SaveOptions(mode=mode)
        else:
            opts = replace(options, mode=mode) if options.mode != mode else options
        if mode == "preserve":
            if self.cst_root is None:
                raise ValueError("Document has no CST root")
            return save_document(path, cst_root=self.cst_root, options=opts)
        if mode == "canonical":
            if self.cst_root is None:
                raise ValueError("Document has no CST root")
            return save_document(path, cst_root=self.cst_root, options=opts)
        raise ValueError(f"Unknown save mode: {mode}")

    def refresh_ast(self) -> None:
        if self.cst_root is None:
            raise ValueError("Document has no CST root")
        self.ast_root = lower_root(self.cst_root)
