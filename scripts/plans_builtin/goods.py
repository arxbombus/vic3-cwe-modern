from __future__ import annotations

from pathlib import Path

from clausewitz import ClausewitzDocument
from clausewitz.nodes import ClausewitzEntry, ClausewitzBlock, ClausewitzScalarValue

from plan_api import ExecutionPlan, ParamSpec, PlanSpec
from plans_builtin.common import (
    EditContext,
    EditPlan,
    EditRule,
    make_ast_execution_plan,
)

GOODS_COST_FACTOR = 1.5


def _build_goods_plan() -> EditPlan:
    def is_goods_cost(
        path: tuple[str, ...], entry: ClausewitzEntry, parent: ClausewitzBlock | None
    ) -> bool:
        _ = path
        _ = parent
        return (
            entry.key == "cost"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_cost(
        path: tuple[str, ...],
        entry: ClausewitzEntry,
        parent: ClausewitzBlock | None,
        context: EditContext,
    ) -> None:
        _ = path
        _ = parent
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for scaling")
        if context.factor == 0:
            raise ValueError("Scaling factor cannot be 0")
        scaled = entry.value.value * context.factor
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_goods_cost",
            description="Scale goods cost by factor",
            predicate=is_goods_cost,
            apply=scale_cost,
        )
    ]
    return EditPlan(name="goods", edits=edits)


def _validate_factor(value: float) -> float:
    if value == 0:
        raise ValueError("factor cannot be 0")
    return value


def get_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="factor",
            kind="float",
            default=GOODS_COST_FACTOR,
            help="Scale factor (multiply by)",
            validate=_validate_factor,
        )
    ]
    plan = _build_goods_plan()

    def build(values: dict) -> ExecutionPlan:
        factor = float(values["factor"])

        def describe(_: dict) -> str:
            return f"Scale goods cost by {factor}"

        def context_builder(_document: ClausewitzDocument) -> EditContext:
            return EditContext(factor=factor)

        return make_ast_execution_plan(
            "goods",
            plan,
            describe=describe,
            context_builder=context_builder,
        )

    return PlanSpec(
        id="goods",
        title="Goods",
        default_dir=Path("common") / "goods",
        params=params,
        build=build,
    )
