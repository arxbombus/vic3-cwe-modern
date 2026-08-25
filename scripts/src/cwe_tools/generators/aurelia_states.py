from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cwe_tools.config import AppConfig
from cwe_tools.paradox.localization import format_localization, parse_localization
from cwe_tools.paradox.script import format_script, parse_script
from cwe_tools.sources.resolver import SourceResolver
from cwe_tools.victoria3.map_locators import Locator, set_locator
from cwe_tools.victoria3.state_regions import (
    StateRegionDefinition,
    parse_state_region_file,
    remove_value_from_field,
)


def _as_float(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must contain numbers, not booleans")

    if isinstance(value, (int, float, str)):
        return float(value)

    raise TypeError(
        f"{name} must contain only numeric values, got {type(value).__name__}"
    )


def _vec3(value: object, *, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly 3 values")

    return (
        _as_float(value[0], name=name),
        _as_float(value[1], name=name),
        _as_float(value[2], name=name),
    )


def _vec4(value: object, *, name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must contain exactly 4 values")

    return (
        _as_float(value[0], name=name),
        _as_float(value[1], name=name),
        _as_float(value[2], name=name),
        _as_float(value[3], name=name),
    )


@dataclass
class AureliaContribution:
    new_states: dict[str, StateRegionDefinition] = field(default_factory=dict)
    disable_states: set[str] = field(default_factory=set)
    extra_outputs: dict[str, str] = field(default_factory=dict)


def _load_effective_entity_file(
    *,
    config: AppConfig,
    resolver: SourceResolver,
    entity_name: str,
) -> str:
    entity = config.entity(entity_name)
    if entity.base_source is None:
        raise ValueError(f"Entity {entity_name!r} has no base_source")

    text = resolver.resolve(entity.base_source).read_text(entity.path)
    if entity.overlay_source is not None:
        overlay = resolver.resolve(entity.overlay_source)
        with contextlib.suppress(FileNotFoundError, OSError):
            text = overlay.read_text(entity.path)
    return text


def build_aurelia_contribution(
    *,
    scripts_root: Path,
    config: AppConfig,
    manifest: dict[str, Any],
    effective_states: dict[str, StateRegionDefinition],
) -> AureliaContribution:
    raw = manifest.get("aurelia")
    if not isinstance(raw, dict) or not raw.get("enabled", False):
        return AureliaContribution()

    states_input = scripts_root / str(raw["states_input"])
    localization_input = scripts_root / str(raw["localization_input"])
    states_output = str(raw["states_output"])
    localization_output = str(raw["localization_output"])

    states_text = states_input.read_text(encoding="utf-8-sig")
    new_definitions = parse_state_region_file(states_output, states_text)
    new_states = {state.name: state for state in new_definitions}

    # Apply surgical edits to surviving source states before replacement files
    # are rendered. No generic schema/parser knowledge is required here.
    remove_values = raw.get("remove_values", {})
    if isinstance(remove_values, dict):
        for state_name, fields in remove_values.items():
            state = effective_states.get(state_name)
            if state is None:
                raise KeyError(
                    f"Aurelia remove_values targets unknown state {state_name}"
                )
            if not isinstance(fields, dict):
                continue
            for field_name, values in fields.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    remove_value_from_field(state, str(field_name), str(value))

    outputs = {
        states_output: format_script(parse_script(states_text)),
        localization_output: format_localization(
            parse_localization(localization_input.read_text(encoding="utf-8-sig"))
        ),
    }

    resolver = SourceResolver(config)
    locators = raw.get("locators", {})
    if isinstance(locators, dict):
        for _kind, locator_config in locators.items():
            if not isinstance(locator_config, dict):
                continue
            entity_name = str(locator_config["source_entity"])
            output_path = str(locator_config["output"])
            source_text = _load_effective_entity_file(
                config=config,
                resolver=resolver,
                entity_name=entity_name,
            )
            document = parse_script(source_text)
            instances = locator_config.get("instances", {})
            if isinstance(instances, dict):
                for raw_id, values in instances.items():
                    if not isinstance(values, dict):
                        continue
                    locator = Locator(
                        id=int(raw_id),
                        position=_vec3(
                            values.get("position"),
                            name=f"locator {raw_id} position",
                        ),
                        rotation=_vec4(
                            values.get("rotation"),
                            name=f"locator {raw_id} rotation",
                        ),
                        scale=_vec3(
                            values.get("scale", [1.0, 1.0, 1.0]),
                            name=f"locator {raw_id} scale",
                        ),
                    )
                    set_locator(document, locator)
            outputs[output_path] = format_script(document)

    return AureliaContribution(
        new_states=new_states,
        disable_states={str(value) for value in raw.get("disable_states", [])},
        extra_outputs=outputs,
    )
