"""
Saving utility:
- preserve: replay CST losslessly (preserves formatting/comments)
- canonical: format CST while preserving comments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clausewitz.core.cst import CstBlock
from clausewitz.format.cst_formatter import ClausewitzCstFormatter
from clausewitz.format.lossless import print_cst
from clausewitz.format.policy import FormatPolicy

SaveMode = Literal["preserve", "canonical"]


@dataclass(frozen=True, slots=True)
class SaveOptions:
    mode: SaveMode = "preserve"
    encoding: str = "utf-8"
    format_policy: FormatPolicy = FormatPolicy(max_width=100, indent=4)
    preserve_comments: bool = True
    preserve_trivia: bool = False


def save_document(
    path: str | Path,
    *,
    cst_root: CstBlock,
    options: SaveOptions = SaveOptions(),
) -> str:
    """
    Returns the text written (also writes to disk).

    preserve:
      - requires cst_root
    canonical:
      - requires cst_root
    """
    p = Path(path)

    if options.mode == "preserve":
        new_text = print_cst(cst_root)
        p.write_text(new_text, encoding=options.encoding)
        return new_text

    if options.mode == "canonical":
        formatter = ClausewitzCstFormatter(
            options.format_policy,
            preserve_comments=options.preserve_comments,
            preserve_trivia=options.preserve_trivia,
        )
        new_text = formatter.format(cst_root)
        p.write_text(new_text, encoding=options.encoding)
        return new_text

    raise ValueError(f"Unknown save mode: {options.mode}")
