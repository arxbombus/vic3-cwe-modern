"""High-level Clausewitz document wrapper (parse -> CST/AST -> edits -> save)."""

from dataclasses import dataclass
from pathlib import Path

from clausewitz.core import ClausewitzParser, CstBlock, DocumentSchema, ParserConfig
from clausewitz.edit import CstEditSession
from clausewitz.format import ClausewitzCstFormatter, print_cst
from clausewitz.io import SaveMode, SaveOptions
from clausewitz.model import Block, Entry, lower_root


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

    def save(
        self,
        path: str | Path,
        *,
        mode: SaveMode = "preserve",
        options: SaveOptions | None = None,
    ) -> str:
        opts = options or SaveOptions(mode=mode)
        if mode == "preserve":
            if self.cst_root is None:
                raise ValueError("Document has no CST root")
            new_text = print_cst(self.cst_root)
            Path(path).write_text(new_text, encoding=opts.encoding)
            return new_text
        if mode == "canonical":
            if self.cst_root is None:
                raise ValueError("Document has no CST root")
            formatter = ClausewitzCstFormatter(opts.format_policy)
            new_text = formatter.format(self.cst_root)
            Path(path).write_text(new_text, encoding=opts.encoding)
            return new_text
        raise ValueError(f"Unknown save mode: {mode}")

    def refresh_ast(self) -> None:
        if self.cst_root is None:
            raise ValueError("Document has no CST root")
        self.ast_root = lower_root(self.cst_root)
