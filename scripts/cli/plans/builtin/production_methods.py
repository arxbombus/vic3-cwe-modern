from __future__ import annotations

from pathlib import Path

from clausewitz import ClausewitzDocument
from clausewitz.model import Block, ScalarValue, TaggedValue
from clausewitz.query import find_entries, match_segment

from cli.ops import scale_numeric_values

from ..spec import EditInfo, ParamKind, ParamSpec, PlanExecution, PlanResult, PlanSpec

PRODUCTION_METHODS_EMPLOYMENT_FACTOR = 2.0
PRODUCTION_METHODS_TECH_INPUT_THRESHOLD = 3.0
PRODUCTION_METHODS_HIGH_TECH_INPUT_THRESHOLD = 4.0
PRODUCTION_METHODS_TECH_OUTPUT_MULT = 1.5
PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT = 2.5

CHOICE_ALL = "ALL"
CHOICE_SCALE_EMPLOYMENT = "scale building_employment_add"
CHOICE_ADD_TECH_INPUT = "add technology services input"
CHOICE_ADD_HIGH_INPUT = "add high technology services input"
CHOICE_SCALE_TECH = "scale goods_output_mult (technology)"
CHOICE_SCALE_HIGH = "scale goods_output_mult (high technology)"


def _validate_factor(value: float) -> float:
    if value == 0:
        raise ValueError("factor cannot be 0")
    return value


def production_methods_plan() -> PlanSpec:
    params = [
        ParamSpec(
            name="edits",
            kind=ParamKind.multiselect,
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
            kind=ParamKind.float,
            default=PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
            help="Scale factor (multiply by)",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_EMPLOYMENT in values.get("edits", set()),
        ),
        ParamSpec(
            name="tech_output_mult",
            kind=ParamKind.float,
            default=PRODUCTION_METHODS_TECH_OUTPUT_MULT,
            help="Technology goods_output_mult multiplier",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_TECH in values.get("edits", set()),
        ),
        ParamSpec(
            name="high_output_mult",
            kind=ParamKind.float,
            default=PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT,
            help="High technology goods_output_mult multiplier",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_SCALE_HIGH in values.get("edits", set()),
        ),
        ParamSpec(
            name="tech_threshold",
            kind=ParamKind.float,
            default=PRODUCTION_METHODS_TECH_INPUT_THRESHOLD,
            help="Professional services threshold for technology input",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_ADD_TECH_INPUT in values.get("edits", set()),
        ),
        ParamSpec(
            name="high_threshold",
            kind=ParamKind.float,
            default=PRODUCTION_METHODS_HIGH_TECH_INPUT_THRESHOLD,
            help="Professional services threshold for high technology input",
            validate=_validate_factor,
            visible_if=lambda values: CHOICE_ALL in values.get("edits", set())
            or CHOICE_ADD_HIGH_INPUT in values.get("edits", set()),
        ),
    ]

    edits = [
        EditInfo(
            name="scale_building_employment_add",
            description="Scale building_employment_*_add under building_modifiers/level_scaled by factor",
        ),
        EditInfo(
            name="add_technology_services_input",
            description="Add goods_input_technology_services_add when professional services > threshold",
        ),
        EditInfo(
            name="add_high_technology_services_input",
            description="Add goods_input_high_technology_services_add when professional services > threshold",
        ),
        EditInfo(
            name="scale_goods_output_mult",
            description="Scale goods_output_mult under building_modifiers/(unscaled|workforce_scaled) by tech multiplier",
        ),
    ]

    def build(values: dict) -> PlanExecution:
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

        factor = float(values.get("employment_factor", PRODUCTION_METHODS_EMPLOYMENT_FACTOR))
        tech_output_mult = float(values.get("tech_output_mult", PRODUCTION_METHODS_TECH_OUTPUT_MULT))
        high_output_mult = float(values.get("high_output_mult", PRODUCTION_METHODS_HIGH_TECH_OUTPUT_MULT))
        tech_threshold = float(values.get("tech_threshold", PRODUCTION_METHODS_TECH_INPUT_THRESHOLD))
        high_threshold = float(values.get("high_threshold", PRODUCTION_METHODS_HIGH_TECH_INPUT_THRESHOLD))

        def describe(_: dict) -> str:
            if not selected_names:
                return "No production_methods edits selected"
            details = []
            if "scale_building_employment_add" in selected_names:
                details.append(f"employment x{factor}")
            if "add_technology_services_input" in selected_names:
                details.append(f"add technology services input (> {tech_threshold})")
            if "add_high_technology_services_input" in selected_names:
                details.append(f"add high technology services input (> {high_threshold})")
            if scale_tech:
                details.append(f"scale goods_output_mult (tech) x{tech_output_mult}")
            if scale_high:
                details.append(f"scale goods_output_mult (high tech) x{high_output_mult}")
            return "Production methods: " + ", ".join(details)

        def apply(document: ClausewitzDocument) -> PlanResult:
            counts: dict[str, int] = {
                "scale_building_employment_add": 0,
                "add_technology_services_input": 0,
                "add_high_technology_services_input": 0,
                "scale_goods_output_mult": 0,
            }

            if "scale_building_employment_add" in selected_names:
                counts["scale_building_employment_add"] = scale_numeric_values(
                    document,
                    key_pattern="building_employment_*_add",
                    factor=factor,
                    ancestor_suffix_pattern="**.building_modifiers.level_scaled",
                    exclude_key_patterns=(),
                    operator="=",
                )

            if "add_technology_services_input" in selected_names or "add_high_technology_services_input" in selected_names:
                tech_count, high_count = _add_service_inputs(
                    document,
                    tech_threshold=tech_threshold,
                    high_threshold=high_threshold,
                    add_tech="add_technology_services_input" in selected_names,
                    add_high="add_high_technology_services_input" in selected_names,
                )
                counts["add_technology_services_input"] = tech_count
                counts["add_high_technology_services_input"] = high_count

            if "scale_goods_output_mult" in selected_names:
                counts["scale_goods_output_mult"] = _scale_goods_output(
                    document,
                    tech_threshold=tech_threshold,
                    high_threshold=high_threshold,
                    tech_output_mult=tech_output_mult,
                    high_output_mult=high_output_mult,
                    enable_add_tech="add_technology_services_input" in selected_names,
                    enable_add_high="add_high_technology_services_input" in selected_names,
                    scale_tech=scale_tech,
                    scale_high=scale_high,
                )

            return PlanResult(counts=counts)

        return PlanExecution(
            name="production_methods",
            edits=edits,
            describe=describe,
            apply=apply,
        )

    return PlanSpec(
        id="production_methods",
        title="Production Methods",
        default_paths=[Path("common") / "production_methods"],
        params=params,
        build=build,
    )


def _add_service_inputs(
    document: ClausewitzDocument,
    *,
    tech_threshold: float,
    high_threshold: float,
    add_tech: bool,
    add_high: bool,
) -> tuple[int, int]:
    tech_count = 0
    high_count = 0
    for ref in find_entries(
        document.root,
        key_pattern="level_scaled",
        ancestor_suffix_pattern="**.building_modifiers",
        exclude_key_patterns=(),
    ):
        block = _unwrap_block(ref.entry.value)
        if block is None:
            continue
        prof_value, prof_raw = _find_scalar_value(block, "goods_input_professional_services_add")
        if prof_value is None or prof_raw is None:
            continue
        if add_tech and prof_value > tech_threshold and not _block_has_key(block, "goods_input_technology_services_add"):
            raw_value = _format_number_like(prof_raw, prof_value - 2.0)
            document.session.insert_entry_end_of_block_ast(
                ref, f"goods_input_technology_services_add = {raw_value}"
            )
            tech_count += 1
        if add_high and prof_value > high_threshold and not _block_has_key(block, "goods_input_high_technology_services_add"):
            raw_value = _format_number_like(prof_raw, prof_value - 3.0)
            document.session.insert_entry_end_of_block_ast(
                ref, f"goods_input_high_technology_services_add = {raw_value}"
            )
            high_count += 1
    return tech_count, high_count


def _scale_goods_output(
    document: ClausewitzDocument,
    *,
    tech_threshold: float,
    high_threshold: float,
    tech_output_mult: float,
    high_output_mult: float,
    enable_add_tech: bool,
    enable_add_high: bool,
    scale_tech: bool,
    scale_high: bool,
) -> int:
    multiplier_map: dict[str, float] = {}
    for entry in document.root.entries:
        pm_name = entry.key
        pm_block = _unwrap_block(entry.value)
        if pm_block is None:
            continue
        level_scaled = _find_child_block(pm_block, "building_modifiers", "level_scaled")
        if level_scaled is None:
            continue
        prof_value, _ = _find_scalar_value(level_scaled, "goods_input_professional_services_add")
        has_tech = _block_has_key(level_scaled, "goods_input_technology_services_add")
        has_high = _block_has_key(level_scaled, "goods_input_high_technology_services_add")
        if prof_value is not None:
            if enable_add_high and prof_value > high_threshold:
                has_high = True
            if enable_add_tech and prof_value > tech_threshold:
                has_tech = True
        multiplier = None
        if scale_high and has_high:
            multiplier = high_output_mult
        elif scale_tech and has_tech:
            multiplier = tech_output_mult
        if multiplier is not None:
            multiplier_map[pm_name] = multiplier

    count = 0
    for ref in find_entries(
        document.root,
        key_pattern="goods_output*",
        ancestor_suffix_pattern="**.building_modifiers.*",
        exclude_key_patterns=(),
    ):
        if not ref.ancestors:
            continue
        scope = ref.ancestors[-1]
        if scope not in {"unscaled", "workforce_scaled"}:
            continue
        if not match_segment("goods_output*", ref.entry.key):
            continue
        scalar = ref.entry.value
        if not isinstance(scalar, ScalarValue):
            continue
        multiplier = multiplier_map.get(ref.ancestors[0])
        if multiplier is None:
            continue
        old_num = _parse_number_raw(scalar.raw)
        if old_num is None:
            continue
        new_raw = _format_number_like(scalar.raw, old_num * multiplier)
        document.session.replace_entry_value_ast(ref, new_raw)
        count += 1
    return count


def _find_child_block(block: Block, *keys: str) -> Block | None:
    current = block
    for key in keys:
        next_block = None
        for entry in current.entries:
            if entry.key != key:
                continue
            next_block = _unwrap_block(entry.value)
            break
        if next_block is None:
            return None
        current = next_block
    return current


def _unwrap_block(value: object) -> Block | None:
    if isinstance(value, Block):
        return value
    if isinstance(value, TaggedValue) and isinstance(value.value, Block):
        return value.value
    return None


def _block_has_key(block: Block, key: str) -> bool:
    return any(entry.key == key for entry in block.entries)


def _find_scalar_value(block: Block, key: str) -> tuple[float | None, str | None]:
    for entry in block.entries:
        if entry.key != key:
            continue
        if isinstance(entry.value, ScalarValue):
            raw = entry.value.raw
            num = _parse_number_raw(raw)
            return num, raw
    return None, None


def _parse_number_raw(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _format_number_like(old_raw: str, new_value: float) -> str:
    s = old_raw.strip()
    if "." not in s and "e" not in s and "E" not in s:
        rounded = int(round(new_value))
        if abs(new_value - rounded) < 1e-9:
            return str(rounded)
        return str(new_value)
    if "." in s:
        decimals = len(s.split(".", 1)[1])
        return f"{new_value:.{decimals}f}"
    return str(new_value)
