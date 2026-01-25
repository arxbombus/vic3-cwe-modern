from __future__ import annotations

from pathlib import Path

from plan_api import ExecutionPlan, ParamSpec, PlanSpec
from plans_builtin.common import TextEditPlan, TextEditRule, make_text_execution_plan, scale_key_value_text

POP_TYPES_WAGE_WEIGHT_FACTOR = 1.5
POP_TYPES_DEPENDENT_WAGE_FACTOR = 0.25

CHOICE_ALL = "ALL"
CHOICE_WAGE_WEIGHT = "only wage_weight"
CHOICE_DEPENDENT_WAGE = "only dependent_wage"


def _build_text_plan(
    wage_weight_factor: float, dependent_wage_factor: float, selected: set[str]
) -> TextEditPlan:
    edits: list[TextEditRule] = []
    if "scale_wage_weight" in selected:
        edits.append(
            TextEditRule(
                name="scale_wage_weight",
                description="Multiply wage_weight by factor",
                apply=lambda text: scale_key_value_text(text, "wage_weight", wage_weight_factor),
            )
        )
    if "scale_dependent_wage" in selected:
        edits.append(
            TextEditRule(
                name="scale_dependent_wage",
                description="Multiply dependent_wage by factor",
                apply=lambda text: scale_key_value_text(text, "dependent_wage", dependent_wage_factor),
            )
        )
    return TextEditPlan(name="pop_types", edits=edits)


def _validate_factor(value: float) -> float:
    if value == 0:
        raise ValueError("factor cannot be 0")
    return value


def get_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="edits",
            kind="multiselect",
            default=[CHOICE_ALL],
            choices=[CHOICE_ALL, CHOICE_WAGE_WEIGHT, CHOICE_DEPENDENT_WAGE],
            help="Select pop_types edits",
        ),
        ParamSpec(
            name="wage_weight_factor",
            kind="float",
            default=POP_TYPES_WAGE_WEIGHT_FACTOR,
            help="wage_weight factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_WAGE_WEIGHT in values.get("edits", set()),
        ),
        ParamSpec(
            name="dependent_wage_factor",
            kind="float",
            default=POP_TYPES_DEPENDENT_WAGE_FACTOR,
            help="dependent_wage factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_DEPENDENT_WAGE in values.get("edits", set()),
        ),
    ]

    def build(values: dict) -> ExecutionPlan:
        selection = set(values.get("edits") or set())
        selected_names: set[str] = set()
        if CHOICE_ALL in selection:
            selected_names = {"scale_wage_weight", "scale_dependent_wage"}
        else:
            if CHOICE_WAGE_WEIGHT in selection:
                selected_names.add("scale_wage_weight")
            if CHOICE_DEPENDENT_WAGE in selection:
                selected_names.add("scale_dependent_wage")

        wage_weight_factor = float(values.get("wage_weight_factor", POP_TYPES_WAGE_WEIGHT_FACTOR))
        dependent_wage_factor = float(values.get("dependent_wage_factor", POP_TYPES_DEPENDENT_WAGE_FACTOR))
        plan = _build_text_plan(wage_weight_factor, dependent_wage_factor, selected_names)

        def describe(_: dict) -> str:
            if not selected_names:
                return "No pop_types edits selected"
            details = []
            if "scale_wage_weight" in selected_names:
                details.append(f"wage_weight x{wage_weight_factor}")
            if "scale_dependent_wage" in selected_names:
                details.append(f"dependent_wage x{dependent_wage_factor}")
            return "Scale pop types: " + ", ".join(details)

        return make_text_execution_plan(
            "pop_types",
            plan,
            describe=describe,
        )

    return PlanSpec(
        id="pop_types",
        title="Pop Types",
        default_dir=Path("common") / "pop_types",
        params=params,
        build=build,
    )
