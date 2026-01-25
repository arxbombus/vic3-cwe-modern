from __future__ import annotations

import math
from pathlib import Path

from clausewitz.nodes import (
    ClausewitzBlock,
    ClausewitzEntry,
    ClausewitzScalarValue,
)

from clausewitz import ClausewitzDocument
from plan_api import ExecutionPlan, ParamSpec, PlanSpec
from plans_builtin.common import (
    EditContext,
    EditPlan,
    EditRule,
    find_wealth_range,
    make_ast_execution_plan,
    parse_wealth_level,
)

BUY_PACKAGES_CURVE_MAX = 2.0
BUY_PACKAGES_CURVE_POWER = 1.0


def _build_buy_packages_plan() -> EditPlan:
    def is_popneed_goods(
        path: tuple[str, ...], entry: ClausewitzEntry, parent: ClausewitzBlock | None
    ) -> bool:
        if len(path) < 3 or path[-2] != "goods":
            return False
        if parse_wealth_level(path[-3]) is None:
            return False
        key = str(entry.key)
        _ = parent
        return (
            key.startswith("popneed_")
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_popneed(
        path: tuple[str, ...],
        entry: ClausewitzEntry,
        parent: ClausewitzBlock | None,
        context: EditContext,
    ) -> None:
        _ = parent
        wealth_level = parse_wealth_level(path[-3])
        if wealth_level is None:
            return
        if context.wealth_min is None or context.wealth_max is None:
            multiplier = 1.0
        elif context.wealth_max <= context.wealth_min:
            multiplier = 1.0
        else:
            t = (wealth_level - context.wealth_min) / (context.wealth_max - context.wealth_min)
            curve_max = context.curve_max if context.curve_max is not None else 2.0
            curve_power = context.curve_power if context.curve_power is not None else 1.0
            multiplier = math.pow(curve_max, t**curve_power)
            if multiplier > curve_max:
                multiplier = curve_max

        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for popneed scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for popneed scaling")
        scaled = int(entry.value.value * multiplier)
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_popneed_goods",
            description="Scale popneed_* by exponential wealth curve (max 2x)",
            predicate=is_popneed_goods,
            apply=scale_popneed,
        )
    ]
    return EditPlan(name="buy_packages", edits=edits)


def _build_buy_packages_context_builder(curve_max: float, curve_power: float):
    def builder(document: ClausewitzDocument, factor: float) -> EditContext:
        wealth_min, wealth_max = find_wealth_range(document)
        return EditContext(
            factor=factor,
            wealth_min=wealth_min,
            wealth_max=wealth_max,
            curve_max=curve_max,
            curve_power=curve_power,
        )

    return builder


def _validate_curve_max(value: float) -> float:
    if value < 1:
        raise ValueError("max multiplier must be bigger than 1")
    return value


def _validate_curve_power(value: float) -> float:
    if value <= 0:
        raise ValueError("curve power must be greater than 0")
    return value


def get_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="curve_max",
            kind="float",
            default=BUY_PACKAGES_CURVE_MAX,
            help="Max multiplier (<= 2x)",
            validate=_validate_curve_max,
        ),
        ParamSpec(
            name="curve_power",
            kind="float",
            default=BUY_PACKAGES_CURVE_POWER,
            help="Curve power (higher = richer spend more)",
            validate=_validate_curve_power,
        ),
    ]
    base_plan = _build_buy_packages_plan()

    def build(values: dict) -> ExecutionPlan:
        curve_max = float(values["curve_max"])
        curve_power = float(values["curve_power"])
        context_builder = _build_buy_packages_context_builder(curve_max, curve_power)

        def describe(_: dict) -> str:
            return f"Scale pop needs with curve max {curve_max}, power {curve_power}"

        def context_for_document(document: ClausewitzDocument) -> EditContext:
            return context_builder(document, factor=1.0)

        return make_ast_execution_plan(
            "buy_packages",
            base_plan,
            describe=describe,
            context_builder=context_for_document,
        )

    return PlanSpec(
        id="buy_packages",
        title="Buy Packages",
        default_dir=Path("common") / "buy_packages",
        params=params,
        build=build,
    )
