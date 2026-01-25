"""Formatting policy shared by CST formatters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormatPolicy:
    max_width: int = 100
    indent: int = 4

    # Heuristics (canonical):
    inline_list_max_items: int = 2
    inline_block_max_entries: int = 1

    # Canonical output tweaks:
    trim_float_trailing_zero: bool = True


__all__ = ["FormatPolicy"]
