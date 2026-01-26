from __future__ import annotations

from typing import Iterable

from .spec import PlanSpec
from .builtin.goods import goods_plan
from .builtin.pop_types import pop_types_plan
from .builtin.production_methods import production_methods_plan


def registry() -> dict[str, PlanSpec]:
    plans = [
        goods_plan(),
        pop_types_plan(),
        production_methods_plan(),
    ]
    return {plan.id: plan for plan in plans}


def list_plans() -> list[PlanSpec]:
    return list(registry().values())


def load_plan(plan_id: str) -> PlanSpec | None:
    return registry().get(plan_id)


def list_plan_ids() -> list[str]:
    return sorted(registry().keys())


def find_plans(plan_ids: Iterable[str]) -> list[PlanSpec]:
    reg = registry()
    plans: list[PlanSpec] = []
    for plan_id in plan_ids:
        plan = reg.get(plan_id)
        if plan is None:
            raise ValueError(f"Unknown plan '{plan_id}'")
        plans.append(plan)
    return plans
