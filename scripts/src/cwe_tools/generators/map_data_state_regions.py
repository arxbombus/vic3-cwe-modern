from __future__ import annotations

import fnmatch
import json
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from cwe_tools.config import AppConfig
from cwe_tools.generators.aurelia_states import (
    AureliaContribution,
    build_aurelia_contribution,
)
from cwe_tools.paradox.script.ast import Commented, Script
from cwe_tools.paradox.script.formatter import format_script
from cwe_tools.sources.models import FileSource
from cwe_tools.sources.resolver import SourceResolver
from cwe_tools.victoria3.state_regions import (
    StateRegionDefinition,
    add_arable_resource,
    add_discoverable_resource,
    add_trait,
    adjust_capped_resource,
    multiply_capped_resource,
    multiply_number,
    overlay_states,
    parse_state_region_file,
    remove_arable_resource,
    remove_trait,
    set_number,
    validate_state_regions,
)


@dataclass(frozen=True)
class GenerationPlan:
    outputs: dict[str, str]
    validation_errors: list[str]


def load_manifest(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _ownership_paths(mod_root: Path, manifest: dict[str, Any]) -> set[str]:
    output = manifest.get("output", {})
    if not isinstance(output, dict):
        return set()
    path = mod_root / str(
        output.get("ownership_file", "scripts/.generated/map_data_state_regions.json")
    )
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(value) for value in data.get("files", [])}


def _should_include_overlay_file(
    path: str,
    *,
    entity_directory: str,
    manifest: dict[str, Any],
    owned_paths: set[str],
) -> bool:
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        return True

    name = PurePosixPath(path).name
    include = {str(value) for value in source.get("include_files", [])}
    if name in include or path in include:
        return True

    if path in owned_paths:
        return False

    # If an ownership file exists, exact ownership is authoritative and we no
    # longer need the broad bootstrap patterns.
    if owned_paths:
        return True

    for pattern in source.get("bootstrap_exclude_globs", []):
        if fnmatch.fnmatch(name, str(pattern)) or fnmatch.fnmatch(path, str(pattern)):
            return False
    return True


def _load_source_states(
    source: FileSource,
    directory: str,
    *,
    overlay: bool,
    manifest: dict[str, Any],
    owned_paths: set[str],
) -> list[StateRegionDefinition]:
    result: list[StateRegionDefinition] = []
    for path in source.list_files(directory, suffix=".txt"):
        if overlay and not _should_include_overlay_file(
            path,
            entity_directory=directory,
            manifest=manifest,
            owned_paths=owned_paths,
        ):
            continue
        text = source.read_text(path)
        result.extend(parse_state_region_file(path, text))
    return result


def load_effective_states(
    *,
    base_source: FileSource,
    overlay_source: FileSource | None,
    directory: str,
    manifest: dict[str, Any],
    owned_paths: set[str],
) -> dict[str, StateRegionDefinition]:
    result: dict[str, StateRegionDefinition] = {}
    for definition in _load_source_states(
        base_source,
        directory,
        overlay=False,
        manifest=manifest,
        owned_paths=set(),
    ):
        if definition.name in result:
            raise ValueError(f"Base source defines {definition.name} more than once")
        result[definition.name] = definition

    if overlay_source is not None:
        overlay_states(
            result,
            _load_source_states(
                overlay_source,
                directory,
                overlay=True,
                manifest=manifest,
                owned_paths=owned_paths,
            ),
        )
    return result


def _apply_global_rules(
    states: dict[str, StateRegionDefinition], manifest: dict[str, Any]
) -> None:
    global_config = manifest.get("global", {})
    if not isinstance(global_config, dict):
        return

    arable_factor = Decimal(str(global_config.get("arable_land_multiplier", 1)))
    resource_factors = global_config.get("capped_resource_multipliers", {})
    if not isinstance(resource_factors, dict):
        resource_factors = {}

    for state in states.values():
        if arable_factor != 1:
            multiply_number(state.block, "arable_land", arable_factor)
        for building, raw_factor in resource_factors.items():
            multiply_capped_resource(state, str(building), Decimal(str(raw_factor)))


def _apply_state_rules(
    states: dict[str, StateRegionDefinition],
    manifest: dict[str, Any],
    *,
    strict: bool = True,
) -> None:
    raw_states = manifest.get("states", {})
    if not isinstance(raw_states, dict):
        return

    for state_name, rules in raw_states.items():
        state = states.get(state_name)
        if state is None:
            if strict:
                raise KeyError(f"Manifest targets unknown state {state_name}")
            continue
        if not isinstance(rules, dict):
            continue

        if "arable_land" in rules:
            set_number(state.block, "arable_land", int(rules["arable_land"]))
        for trait in rules.get("add_traits", []):
            add_trait(state, str(trait))
        for trait in rules.get("remove_traits", []):
            remove_trait(state, str(trait))
        for resource in rules.get("add_arable_resources", []):
            add_arable_resource(state, str(resource))
        for resource in rules.get("remove_arable_resources", []):
            remove_arable_resource(state, str(resource))

        capped = rules.get("capped_resources", {})
        if isinstance(capped, dict):
            for building, operation in capped.items():
                if isinstance(operation, int):
                    operation = {"set": operation}
                if not isinstance(operation, dict):
                    raise TypeError(
                        f"Invalid capped resource rule for {state_name}.{building}"
                    )
                adjust_capped_resource(
                    state,
                    str(building),
                    set_value=int(operation["set"]) if "set" in operation else None,
                    multiply=Decimal(str(operation["multiply"]))
                    if "multiply" in operation
                    else None,
                    add=int(operation["add"]) if "add" in operation else None,
                )

        resources = rules.get("resources", [])
        if isinstance(resources, list):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                add_discoverable_resource(
                    state,
                    building=str(resource["type"]),
                    discovered_amount=int(resource["discovered_amount"])
                    if "discovered_amount" in resource
                    else None,
                    undiscovered_amount=int(resource["undiscovered_amount"])
                    if "undiscovered_amount" in resource
                    else None,
                )


def _replacement_filename(group: str) -> str:
    return f"{group}replace.txt" if group.endswith("_") else f"{group}_replace.txt"


def _render_group(
    states: list[StateRegionDefinition],
    *,
    disabled: set[str],
) -> str:
    entries = []
    for state in sorted(states, key=lambda item: item.name):
        entry = state.assignment
        entries.append(Commented(entry) if state.name in disabled else entry)
    return format_script(Script(entries))


def build_plan(
    *,
    config: AppConfig,
    scripts_root: Path,
    manifest_path: Path,
    base_source_spec: str | None = None,
    overlay_source_spec: str | None = None,
    entity_path: str | None = None,
) -> GenerationPlan:
    manifest = load_manifest(manifest_path)
    generator_config = config.generator("map_data_state_regions")
    entity_name = generator_config.entity or "map_data_state_regions"
    entity = config.entity(entity_name)
    manifest_source = manifest.get("source", {})
    if not isinstance(manifest_source, dict):
        manifest_source = {}

    base_spec = (
        base_source_spec
        or generator_config.base_source
        or str(manifest_source.get("base_source") or "")
        or entity.base_source
    )
    overlay_spec = (
        overlay_source_spec
        or generator_config.overlay_source
        or str(manifest_source.get("overlay_source") or "")
        or entity.overlay_source
    )
    directory = entity_path or str(manifest_source.get("path") or entity.path)
    if not base_spec:
        raise ValueError("No base source configured for map_data_state_regions")

    resolver = SourceResolver(config)
    base_source = resolver.resolve(base_spec)
    overlay_source = resolver.resolve(overlay_spec) if overlay_spec else None
    owned_paths = _ownership_paths(config.mod_root, manifest)
    states = load_effective_states(
        base_source=base_source,
        overlay_source=overlay_source,
        directory=directory,
        manifest=manifest,
        owned_paths=owned_paths,
    )

    # Broad upstream-derived modifications happen first.
    _apply_global_rules(states, manifest)
    # Some per-state rules may target states contributed later (for example
    # Aurelia states), so defer unknown-target validation until contributors load.
    _apply_state_rules(states, manifest, strict=False)

    # Aurelia is an optional contributor to this same state-region pipeline,
    # not a second generator fighting over the same *_replace.txt files.
    aurelia: AureliaContribution = build_aurelia_contribution(
        scripts_root=scripts_root,
        config=config,
        manifest=manifest,
        effective_states=states,
    )

    # Broad resource/state rules should also be able to target newly authored
    # Aurelia states, so apply those rules to the combined active view as well.
    if aurelia.new_states:
        # Global and per-state rules also apply to newly authored Aurelia states,
        # without reapplying rules to the already-processed upstream states.
        _apply_global_rules(aurelia.new_states, manifest)
        _apply_state_rules(aurelia.new_states, manifest, strict=False)

    raw_state_rules = manifest.get("states", {})
    if isinstance(raw_state_rules, dict):
        known_states = set(states) | set(aurelia.new_states)
        unknown = sorted(set(raw_state_rules) - known_states)
        if unknown:
            raise KeyError(f"Manifest targets unknown states: {', '.join(unknown)}")

    output_config = manifest.get("output", {})
    output_directory = str(
        output_config.get("directory", directory)
        if isinstance(output_config, dict)
        else directory
    ).rstrip("/")

    groups: dict[str, list[StateRegionDefinition]] = {}
    for state in states.values():
        groups.setdefault(state.source_group, []).append(state)

    outputs: dict[str, str] = {}
    for group, definitions in sorted(groups.items()):
        base_name = f"{group}.txt"
        replace_name = _replacement_filename(group)
        outputs[f"{output_directory}/{base_name}"] = ""
        outputs[f"{output_directory}/{replace_name}"] = _render_group(
            definitions,
            disabled=aurelia.disable_states,
        )

    outputs.update(aurelia.extra_outputs)

    active_states = {
        name: state
        for name, state in states.items()
        if name not in aurelia.disable_states
    }
    active_states.update(aurelia.new_states)
    validation_errors = validate_state_regions(active_states)
    return GenerationPlan(outputs=outputs, validation_errors=validation_errors)


def _ownership_path(mod_root: Path, manifest: dict[str, Any]) -> Path:
    output = manifest.get("output", {})
    raw = (
        output.get("ownership_file", "scripts/.generated/map_data_state_regions.json")
        if isinstance(output, dict)
        else "scripts/.generated/map_data_state_regions.json"
    )
    return mod_root / str(raw)


def write_plan(plan: GenerationPlan, *, mod_root: Path, manifest_path: Path) -> None:
    if plan.validation_errors:
        raise RuntimeError(
            "State-region validation failed:\n" + "\n".join(plan.validation_errors)
        )
    for relative, content in plan.outputs.items():
        path = mod_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    manifest = load_manifest(manifest_path)
    ownership = _ownership_path(mod_root, manifest)
    ownership.parent.mkdir(parents=True, exist_ok=True)
    ownership.write_text(
        json.dumps({"files": sorted(plan.outputs)}, indent=2) + "\n",
        encoding="utf-8",
    )


def check_plan(plan: GenerationPlan, *, mod_root: Path) -> list[str]:
    problems = list(plan.validation_errors)
    for relative, expected in plan.outputs.items():
        path = mod_root / relative
        if not path.exists():
            problems.append(f"missing generated file: {relative}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            problems.append(f"stale generated file: {relative}")
    return problems
