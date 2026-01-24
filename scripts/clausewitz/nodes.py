"""Node definitions for the Clausewitz intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ClausewitzScalar = str | int | float | bool

ClausewitzOperator = Literal[">", "<", ">=", "<=", "!=", "="]


@dataclass(slots=True)
class ClausewitzScalarValue:
    value: ClausewitzScalar
    raw: str


@dataclass(slots=True)
class ClausewitzComparison:
    left: str
    operator: ClausewitzOperator
    right: ClausewitzScalarValue


@dataclass(slots=True)
class ClausewitzListItem:
    value: "ClausewitzValue"
    leading_trivia: str = ""
    key_trivia: str = ""
    operator_trivia: str = ""
    trailing_trivia: str = ""


@dataclass(slots=True)
class ClausewitzList:
    items: list[ClausewitzListItem] = field(default_factory=list)  # type: ignore
    open_trivia: str = ""
    close_trivia: str = ""

    @property
    def values(self) -> list["ClausewitzValue"]:
        return [item.value for item in self.items]


@dataclass(slots=True)
class ClausewitzEntry:
    key: str
    value: "ClausewitzValue"
    operator: str = "="
    leading_trivia: str = ""
    key_trivia: str = ""
    operator_trivia: str = ""
    value_trivia: str = ""
    trailing_trivia: str = ""


@dataclass(slots=True)
class ClausewitzBlock:
    entries: list[ClausewitzEntry] = field(default_factory=list)  # type: ignore
    leading_trivia: str = ""
    trailing_trivia: str = ""

    def add_entry(
        self,
        key: str,
        value: "ClausewitzValue",
        *,
        operator: str = "=",
        leading_trivia: str = "",
        key_trivia: str = "",
        operator_trivia: str = "",
        value_trivia: str = "",
        trailing_trivia: str = "",
    ) -> None:
        self.entries.append(
            ClausewitzEntry(
                key=key,
                value=value,
                operator=operator,
                leading_trivia=leading_trivia,
                key_trivia=key_trivia,
                operator_trivia=operator_trivia,
                value_trivia=value_trivia,
                trailing_trivia=trailing_trivia,
            )
        )


ClausewitzValue = (
    ClausewitzScalarValue | ClausewitzComparison | ClausewitzList | ClausewitzBlock
)
