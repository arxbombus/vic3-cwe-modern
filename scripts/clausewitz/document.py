"""Generic Clausewitz document container for v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from .nodes import ClausewitzBlock, ClausewitzEntry, ClausewitzValue
from .schema import DocumentSchema


@dataclass
class ClausewitzDocument:
    schema: DocumentSchema
    root: ClausewitzBlock = field(default_factory=ClausewitzBlock)

    def add_entry(self, key: str, value: ClausewitzValue) -> None:
        self.root.add_entry(key, value)

    def entries(self) -> list[ClausewitzEntry]:
        return self.root.entries
