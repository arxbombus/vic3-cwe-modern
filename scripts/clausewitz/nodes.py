"""Node definitions for the Clausewitz intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ClausewitzScalar = str | int | float | bool


@dataclass(slots=True)
class ClausewitzComparison:
    left: ClausewitzScalar
    operator: Literal[">", "<", ">=", "<=", "!=", "="]
    right: ClausewitzScalar


@dataclass(slots=True)
class ClausewitzList:
    values: list["ClausewitzValue"] = field(default_factory=list)


@dataclass(slots=True)
class ClausewitzEntry:
    key: str
    value: "ClausewitzValue"


@dataclass(slots=True)
class ClausewitzBlock:
    entries: list[ClausewitzEntry] = field(default_factory=list)

    def add_entry(self, key: str, value: "ClausewitzValue") -> None:
        self.entries.append(ClausewitzEntry(key=key, value=value))


ClausewitzValue = ClausewitzScalar | ClausewitzComparison | ClausewitzList | ClausewitzBlock
