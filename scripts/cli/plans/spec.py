from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from clausewitz import ClausewitzDocument


class ParamKind(str, Enum):
    bool = "bool"
    int = "int"
    float = "float"
    select = "select"
    multiselect = "multiselect"
    path = "path"
    string = "string"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: ParamKind
    default: Any | None = None
    help: str | None = None
    choices: list[str] | None = None
    validate: Callable[[Any], Any] | None = None
    visible_if: Callable[[dict[str, Any]], bool] | None = None


@dataclass(frozen=True)
class EditInfo:
    name: str
    description: str


@dataclass(frozen=True)
class PlanResult:
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class PlanExecution:
    name: str
    edits: list[EditInfo]
    describe: Callable[[dict[str, Any]], str]
    apply: Callable[[ClausewitzDocument], PlanResult]


@dataclass(frozen=True)
class PlanSpec:
    id: str
    title: str
    default_paths: list[Path]
    params: list[ParamSpec]
    build: Callable[[dict[str, Any]], PlanExecution]
