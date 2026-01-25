from __future__ import annotations

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
    add_block_entry,
    block_has_key,
    find_level_scaled_block,
    find_professional_services_value,
    format_scaled_value,
    in_building_level_scaled,
    make_ast_execution_plan,
)

PRODUCTION_METHODS_EMPLOYMENT_FACTOR = 2.0
PRODUCTION_METHODS_TECH_INPUT_THRESHOLD = 3.0
PRODUCTION_METHODS_HIGH_TECH_INPUT_THRESHOLD = 4.0
PRODUCTION_METHODS_TECH_OUTPUT_MULT = 1.5
PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT = 2.5
PM_TECH_THRESHOLD = 3
PM_HIGH_TECH_THRESHOLD = 5

CHOICE_ALL = "ALL"
CHOICE_SCALE_EMPLOYMENT = "scale building_employment_add"
CHOICE_ADD_TECH_INPUT = "add technology services input"
CHOICE_ADD_HIGH_INPUT = "add high technology services input"
CHOICE_SCALE_TECH = "scale goods_output_mult (technology)"
CHOICE_SCALE_HIGH = "scale goods_output_mult (high technology)"


def _build_production_method_plan() -> EditPlan:
    def is_building_employment(
        path: tuple[str, ...], entry: ClausewitzEntry, parent: ClausewitzBlock | None
    ) -> bool:
        _ = parent
        if not in_building_level_scaled(path):
            return False
        key = str(entry.key)
        return (
            key.startswith("building_employment_")
            and key.endswith("_add")
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_entry(
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
        entry.value.value = int(scaled) if isinstance(entry.value.value, int) else scaled
        entry.value.raw = str(entry.value.value)

    def is_professional_services_add(
        path: tuple[str, ...], entry: ClausewitzEntry, parent: ClausewitzBlock | None
    ) -> bool:
        _ = parent
        if not in_building_level_scaled(path):
            return False
        return (
            entry.key == "goods_input_professional_services_add"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def add_technology_services_input(
        path: tuple[str, ...],
        entry: ClausewitzEntry,
        parent: ClausewitzBlock | None,
        context: EditContext,
    ) -> None:
        _ = path
        if parent is None:
            return
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for tech input add")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for tech input add")
        threshold = context.pm_tech_threshold if context.pm_tech_threshold is not None else PM_TECH_THRESHOLD
        if float(entry.value.value) <= threshold:
            return
        if block_has_key(parent, "goods_input_technology_services_add"):
            return
        scaled_value = float(entry.value.value) - 2.0
        value = int(scaled_value) if isinstance(entry.value.value, int) else scaled_value
        raw_value = format_scaled_value(entry.value.raw, scaled_value)
        add_block_entry(
            parent,
            "goods_input_technology_services_add",
            ClausewitzScalarValue(value=value, raw=raw_value),
        )

    def add_high_technology_services_input(
        path: tuple[str, ...],
        entry: ClausewitzEntry,
        parent: ClausewitzBlock | None,
        context: EditContext,
    ) -> None:
        _ = path
        if parent is None:
            return
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for high tech input add")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for high tech input add")
        threshold = context.pm_high_threshold if context.pm_high_threshold is not None else PM_HIGH_TECH_THRESHOLD
        if float(entry.value.value) <= threshold:
            return
        if block_has_key(parent, "goods_input_high_technology_services_add"):
            return
        scaled_value = float(entry.value.value) - 3.0
        value = int(scaled_value) if isinstance(entry.value.value, int) else scaled_value
        raw_value = format_scaled_value(entry.value.raw, scaled_value)
        add_block_entry(
            parent,
            "goods_input_high_technology_services_add",
            ClausewitzScalarValue(value=value, raw=raw_value),
        )

    def is_goods_output_mult(
        path: tuple[str, ...], entry: ClausewitzEntry, parent: ClausewitzBlock | None
    ) -> bool:
        _ = parent

        def in_building_unscaled(path: tuple[str, ...]) -> bool:
            return len(path) >= 3 and path[-3] == "building_modifiers" and path[-2] == "unscaled"

        def in_workforce_scaled(path: tuple[str, ...]) -> bool:
            return len(path) >= 3 and path[-3] == "building_modifiers" and path[-2] == "workforce_scaled"

        if not in_building_unscaled(path) and not in_workforce_scaled(path):
            return False
        return (
            entry.key == "goods_output_mult"
            or "goods_output" in entry.key
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_goods_output_mult(
        path: tuple[str, ...],
        entry: ClausewitzEntry,
        parent: ClausewitzBlock | None,
        context: EditContext,
    ) -> None:
        _ = parent
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for goods_output_mult")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for goods_output_mult")
        if context.pm_output_multiplier is None:
            return
        pm_name = path[0] if path else ""
        multiplier = context.pm_output_multiplier.get(pm_name)
        if multiplier is None:
            return
        scaled = round(entry.value.value, 3)
        entry.value.value = scaled
        entry.value.raw = str(scaled)

    edits = [
        EditRule(
            name="scale_building_employment_add",
            description="Scale building_employment_*_add under building_modifiers/level_scaled by factor",
            predicate=is_building_employment,
            apply=scale_entry,
        ),
        EditRule(
            name="add_technology_services_input",
            description="Add goods_input_technology_services_add when professional services > threshold",
            predicate=is_professional_services_add,
            apply=add_technology_services_input,
        ),
        EditRule(
            name="add_high_technology_services_input",
            description="Add goods_input_high_technology_services_add when professional services > threshold",
            predicate=is_professional_services_add,
            apply=add_high_technology_services_input,
        ),
        EditRule(
            name="scale_goods_output_mult",
            description="Scale goods_output_mult under building_modifiers/unscaled by tech multiplier",
            predicate=is_goods_output_mult,
            apply=scale_goods_output_mult,
        ),
    ]
    return EditPlan(name="production_methods", edits=edits)


def _build_production_methods_context_builder(
    tech_threshold: float,
    high_threshold: float,
    tech_output_mult: float,
    high_output_mult: float,
    enable_add_tech: bool,
    enable_add_high: bool,
    enable_scale_tech: bool,
    enable_scale_high: bool,
):
    def builder(document: ClausewitzDocument, factor: float) -> EditContext:
        pm_output_multiplier: dict[str, float] = {}
        for entry in document.root.entries:
            pm_name = str(entry.key)
            if not isinstance(entry.value, ClausewitzBlock):
                continue
            level_scaled = find_level_scaled_block(entry.value)
            if level_scaled is None:
                continue
            prof_value = find_professional_services_value(level_scaled)
            has_tech = block_has_key(level_scaled, "goods_input_technology_services_add")
            has_high = block_has_key(level_scaled, "goods_input_high_technology_services_add")
            if prof_value is not None:
                if enable_add_high and prof_value > high_threshold:
                    has_high = True
                if enable_add_tech and prof_value > tech_threshold:
                    has_tech = True

            multiplier: float | None = None
            if enable_scale_high and has_high:
                multiplier = high_output_mult
            elif enable_scale_tech and has_tech:
                multiplier = tech_output_mult
            if multiplier is not None:
                pm_output_multiplier[pm_name] = multiplier

        return EditContext(
            factor=factor,
            pm_output_multiplier=pm_output_multiplier,
            pm_tech_threshold=tech_threshold,
            pm_high_threshold=high_threshold,
            pm_tech_output_mult=tech_output_mult,
            pm_high_output_mult=high_output_mult,
        )

    return builder


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
            choices=[
                CHOICE_ALL,
                CHOICE_SCALE_EMPLOYMENT,
                CHOICE_ADD_TECH_INPUT,
                CHOICE_ADD_HIGH_INPUT,
                CHOICE_SCALE_TECH,
                CHOICE_SCALE_HIGH,
            ],
            help="Select production_methods edits",
        ),
        ParamSpec(
            name="employment_factor",
            kind="float",
            default=PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
            help="Scale factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_EMPLOYMENT in values.get("edits", set()),
        ),
        ParamSpec(
            name="tech_output_mult",
            kind="float",
            default=PRODUCTION_METHODS_TECH_OUTPUT_MULT,
            help="Technology goods_output_mult multiplier",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_TECH in values.get("edits", set()),
        ),
        ParamSpec(
            name="high_output_mult",
            kind="float",
            default=PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT,
            help="High technology goods_output_mult multiplier",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_HIGH in values.get("edits", set()),
        ),
    ]

    base_plan = _build_production_method_plan()

    def build(values: dict) -> ExecutionPlan:
        selection = set(values.get("edits") or set())
        selected_names: set[str] = set()
        scale_tech = False
        scale_high = False
        if CHOICE_ALL in selection:
            selected_names = {
                "scale_building_employment_add",
                "add_technology_services_input",
                "add_high_technology_services_input",
                "scale_goods_output_mult",
            }
            scale_tech = True
            scale_high = True
        else:
            if CHOICE_SCALE_EMPLOYMENT in selection:
                selected_names.add("scale_building_employment_add")
            if CHOICE_ADD_TECH_INPUT in selection:
                selected_names.add("add_technology_services_input")
            if CHOICE_ADD_HIGH_INPUT in selection:
                selected_names.add("add_high_technology_services_input")
            if CHOICE_SCALE_TECH in selection:
                scale_tech = True
            if CHOICE_SCALE_HIGH in selection:
                scale_high = True
            if scale_tech or scale_high:
                selected_names.add("scale_goods_output_mult")

        plan = EditPlan(
            name=base_plan.name,
            edits=[edit for edit in base_plan.edits if edit.name in selected_names],
        )

        factor = float(values.get("employment_factor", PRODUCTION_METHODS_EMPLOYMENT_FACTOR))
        tech_output_mult = float(values.get("tech_output_mult", PRODUCTION_METHODS_TECH_OUTPUT_MULT))
        high_output_mult = float(values.get("high_output_mult", PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT))

        context_builder = _build_production_methods_context_builder(
            PRODUCTION_METHODS_TECH_INPUT_THRESHOLD,
            PRODUCTION_METHODS_HIGH_TECH_INPUT_THRESHOLD,
            tech_output_mult,
            high_output_mult,
            enable_add_tech="add_technology_services_input" in selected_names,
            enable_add_high="add_high_technology_services_input" in selected_names,
            enable_scale_tech=scale_tech,
            enable_scale_high=scale_high,
        )

        def describe(_: dict) -> str:
            if not selected_names:
                return "No production_methods edits selected"
            details = []
            if "scale_building_employment_add" in selected_names:
                details.append(f"employment x{factor}")
            if "add_technology_services_input" in selected_names:
                details.append("add technology services input")
            if "add_high_technology_services_input" in selected_names:
                details.append("add high technology services input")
            if scale_tech:
                details.append(f"scale goods_output_mult (tech) x{tech_output_mult}")
            if scale_high:
                details.append(f"scale goods_output_mult (high tech) x{high_output_mult}")
            return "Production methods: " + ", ".join(details)

        def context_for_document(document: ClausewitzDocument) -> EditContext:
            return context_builder(document, factor)

        return make_ast_execution_plan(
            "production_methods",
            plan,
            describe=describe,
            context_builder=context_for_document,
        )

    return PlanSpec(
        id="production_methods",
        title="Production Methods",
        default_dir=Path("common") / "production_methods",
        params=params,
        build=build,
    )
