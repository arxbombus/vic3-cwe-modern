from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

ParamKind = Literal["bool", "int", "float", "select", "multiselect", "path", "string"]


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
class ApplyResult:
    updated_text: str | None
    counts: dict[str, int] = field(default_factory=dict[str, int])
    warnings: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class ExecutionPlan:
    name: str
    edits: list[EditInfo]
    describe: Callable[[dict[str, Any]], str]
    apply_text: Callable[[str, Path, bool], ApplyResult]


@dataclass(frozen=True)
class PlanSpec:
    id: str
    title: str
    default_dir: Path
    params: list[ParamSpec]
    build: Callable[[dict[str, Any]], ExecutionPlan]
