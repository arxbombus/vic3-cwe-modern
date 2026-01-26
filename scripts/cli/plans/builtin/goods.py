from __future__ import annotations

from pathlib import Path

from cli.ops import scale_numeric_values

from ..spec import EditInfo, ParamKind, ParamSpec, PlanExecution, PlanResult, PlanSpec

GOODS_COST_FACTOR = 1.5


def _validate_factor(value: float) -> float:
    if value == 0:
        raise ValueError("factor cannot be 0")
    return value


def goods_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="factor",
            kind=ParamKind.float,
            default=GOODS_COST_FACTOR,
            help="Scale factor (multiply by)",
            validate=_validate_factor,
        )
    ]

    edits = [
        EditInfo(
            name="scale_goods_cost",
            description="Scale cost by factor",
        )
    ]

    def build(values: dict) -> PlanExecution:
        factor = float(values["factor"])

        def describe(_: dict) -> str:
            return f"Scale goods cost by {factor}"

        def apply(document) -> PlanResult:
            count = scale_numeric_values(
                document,
                key_pattern="cost",
                factor=factor,
                ancestor_suffix_pattern="",
                exclude_key_patterns=(),
                operator="=",
            )
            return PlanResult(counts={"scale_goods_cost": count})

        return PlanExecution(
            name="goods",
            edits=edits,
            describe=describe,
            apply=apply,
        )

    return PlanSpec(
        id="goods",
        title="Goods",
        default_paths=[Path("common") / "goods"],
        params=params,
        build=build,
    )
