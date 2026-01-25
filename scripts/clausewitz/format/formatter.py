"""CST formatter (canonical or preserve) built on CST-aware rendering."""

from __future__ import annotations

from typing import Literal

from clausewitz.core.cst import CstBlock
from clausewitz.format.cst_formatter import ClausewitzCstFormatter
from clausewitz.format.policy import FormatPolicy

Mode = Literal["canonical", "preserve"]

class ClausewitzFormatter:
    def __init__(
        self,
        policy: FormatPolicy | None = None,
        *,
        mode: Mode = "canonical",
        preserve_comments: bool = True,
        preserve_trivia: bool = False,
    ):
        self.policy = policy or FormatPolicy()
        self.mode = mode
        self.preserve_comments = preserve_comments
        self.preserve_trivia = preserve_trivia

    def format(self, root: CstBlock) -> str:
        formatter = ClausewitzCstFormatter(
            self.policy,
            preserve_comments=self.preserve_comments,
            preserve_trivia=self.preserve_trivia or self.mode == "preserve",
        )
        return formatter.format(root)


__all__ = ["ClausewitzFormatter", "FormatPolicy"]
