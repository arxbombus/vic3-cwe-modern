from __future__ import annotations

from pathlib import Path

from cli.ops import scale_numeric_values

from ..spec import EditInfo, ParamKind, ParamSpec, PlanExecution, PlanResult, PlanSpec

POP_TYPES_WAGE_WEIGHT_FACTOR = 1.5
POP_TYPES_DEPENDENT_WAGE_FACTOR = 0.25

CHOICE_ALL = "ALL"
CHOICE_WAGE_WEIGHT = "only wage_weight"
CHOICE_DEPENDENT_WAGE = "only dependent_wage"


def _validate_factor(value: float) -> float:
    if value == 0:
        raise ValueError("factor cannot be 0")
    return value


def pop_types_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="edits",
            kind=ParamKind.multiselect,
            default=[CHOICE_ALL],
            choices=[CHOICE_ALL, CHOICE_WAGE_WEIGHT, CHOICE_DEPENDENT_WAGE],
            help="Select pop_types edits",
        ),
        ParamSpec(
            name="wage_weight_factor",
            kind=ParamKind.float,
            default=POP_TYPES_WAGE_WEIGHT_FACTOR,
            help="wage_weight factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_WAGE_WEIGHT in values.get("edits", set()),
        ),
        ParamSpec(
            name="dependent_wage_factor",
            kind=ParamKind.float,
            default=POP_TYPES_DEPENDENT_WAGE_FACTOR,
            help="dependent_wage factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_DEPENDENT_WAGE in values.get("edits", set()),
        ),
    ]

    edits = [
        EditInfo(
            name="scale_wage_weight",
            description="Multiply wage_weight by factor",
        ),
        EditInfo(
            name="scale_dependent_wage",
            description="Multiply dependent_wage by factor",
        ),
    ]

    def build(values: dict) -> PlanExecution:
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

        def describe(_: dict) -> str:
            if not selected_names:
                return "No pop_types edits selected"
            details = []
            if "scale_wage_weight" in selected_names:
                details.append(f"wage_weight x{wage_weight_factor}")
            if "scale_dependent_wage" in selected_names:
                details.append(f"dependent_wage x{dependent_wage_factor}")
            return "Scale pop types: " + ", ".join(details)

        def apply(document) -> PlanResult:
            counts: dict[str, int] = {"scale_wage_weight": 0, "scale_dependent_wage": 0}
            if "scale_wage_weight" in selected_names:
                counts["scale_wage_weight"] = scale_numeric_values(
                    document,
                    key_pattern="wage_weight",
                    factor=wage_weight_factor,
                    ancestor_suffix_pattern="",
                    exclude_key_patterns=(),
                    operator="=",
                )
            if "scale_dependent_wage" in selected_names:
                counts["scale_dependent_wage"] = scale_numeric_values(
                    document,
                    key_pattern="dependent_wage",
                    factor=dependent_wage_factor,
                    ancestor_suffix_pattern="",
                    exclude_key_patterns=(),
                    operator="=",
                )
            return PlanResult(counts=counts)

        return PlanExecution(
            name="pop_types",
            edits=edits,
            describe=describe,
            apply=apply,
        )

    return PlanSpec(
        id="pop_types",
        title="Pop Types",
        default_paths=[Path("common") / "pop_types"],
        params=params,
        build=build,
    )
