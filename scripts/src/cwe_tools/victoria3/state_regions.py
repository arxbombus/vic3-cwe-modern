from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import PurePosixPath

from cwe_tools.paradox.script.ast import Assignment, Block, Scalar, Script
from cwe_tools.paradox.script.edit import (
    add_scalar_value,
    append_assignment,
    find_assignment,
    find_assignments,
    get_block,
    quoted,
    remove_scalar_value,
    scalar,
    scalar_values,
    set_assignment,
)
from cwe_tools.paradox.script.parser import parse_script


@dataclass
class StateRegionDefinition:
    name: str
    assignment: Assignment
    source_path: str
    source_group: str

    @property
    def block(self) -> Block:
        if not isinstance(self.assignment.value, Block):
            raise TypeError(f"{self.name} is not a block")
        return self.assignment.value


def source_group(path: str) -> str:
    stem = PurePosixPath(path).stem
    return stem.removesuffix("_replace")


def parse_state_region_file(path: str, text: str) -> list[StateRegionDefinition]:
    script = parse_script(text)
    result: list[StateRegionDefinition] = []
    for entry in script.entries:
        if (
            isinstance(entry, Assignment)
            and entry.key.startswith("STATE_")
            and isinstance(entry.value, Block)
        ):
            result.append(
                StateRegionDefinition(
                    name=entry.key,
                    assignment=entry,
                    source_path=path,
                    source_group=source_group(path),
                )
            )
    return result


def overlay_states(
    base: dict[str, StateRegionDefinition],
    overlay: list[StateRegionDefinition],
) -> None:
    for definition in overlay:
        existing = base.get(definition.name)
        if existing is not None:
            # Preserve the vanilla group so complete *_replace.txt files are
            # emitted back into the correct geographical source file.
            definition.source_group = existing.source_group
        base[definition.name] = definition


def assignment_scalar(block: Block, key: str) -> Scalar | None:
    assignment = find_assignment(block, key)
    return (
        assignment.value
        if assignment and isinstance(assignment.value, Scalar)
        else None
    )


def set_number(block: Block, key: str, value: int | float | Decimal) -> None:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        text = text or "0"
    else:
        text = str(value)
    set_assignment(block, key, scalar(text))


def multiply_number(block: Block, key: str, factor: Decimal) -> bool:
    value = assignment_scalar(block, key)
    if value is None:
        return False
    current = Decimal(value.text)
    new = (current * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    set_number(block, key, new)
    return True


def ensure_list_block(block: Block, key: str) -> Block:
    existing = get_block(block, key)
    if existing is not None:
        return existing
    created = Block()
    set_assignment(block, key, created)
    return created


def add_trait(state: StateRegionDefinition, trait: str) -> bool:
    return add_scalar_value(
        ensure_list_block(state.block, "traits"), trait, quoted_value=True
    )


def remove_trait(state: StateRegionDefinition, trait: str) -> bool:
    block = get_block(state.block, "traits")
    return remove_scalar_value(block, trait) if block is not None else False


def add_arable_resource(state: StateRegionDefinition, building: str) -> bool:
    return add_scalar_value(
        ensure_list_block(state.block, "arable_resources"),
        building,
        quoted_value=True,
    )


def remove_arable_resource(state: StateRegionDefinition, building: str) -> bool:
    block = get_block(state.block, "arable_resources")
    return remove_scalar_value(block, building) if block is not None else False


def set_capped_resource(
    state: StateRegionDefinition, building: str, amount: int
) -> None:
    capped = ensure_list_block(state.block, "capped_resources")
    set_assignment(capped, building, scalar(amount))


def adjust_capped_resource(
    state: StateRegionDefinition,
    building: str,
    *,
    set_value: int | None = None,
    multiply: Decimal | None = None,
    add: int | None = None,
) -> bool:
    capped = get_block(state.block, "capped_resources")
    if capped is None:
        if set_value is None and add is None:
            return False
        capped = ensure_list_block(state.block, "capped_resources")

    existing = assignment_scalar(capped, building)
    current = Decimal(existing.text) if existing is not None else Decimal(0)
    if set_value is not None:
        current = Decimal(set_value)
    if multiply is not None:
        current *= multiply
    if add is not None:
        current += Decimal(add)
    new = current.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    set_assignment(capped, building, scalar(int(new)))
    return True


def multiply_capped_resource(
    state: StateRegionDefinition,
    building: str,
    factor: Decimal,
) -> bool:
    capped = get_block(state.block, "capped_resources")
    if capped is None:
        return False
    return multiply_number(capped, building, factor)


def add_discoverable_resource(
    state: StateRegionDefinition,
    *,
    building: str,
    discovered_amount: int | None = None,
    undiscovered_amount: int | None = None,
) -> None:
    # Replace an existing resource block with the same `type` if present.
    for resource in find_assignments(state.block, "resource"):
        if not isinstance(resource.value, Block):
            continue
        type_value = assignment_scalar(resource.value, "type")
        if type_value is None or type_value.text != building:
            continue
        if discovered_amount is not None:
            set_assignment(
                resource.value, "discovered_amount", scalar(discovered_amount)
            )
        if undiscovered_amount is not None:
            set_assignment(
                resource.value, "undiscovered_amount", scalar(undiscovered_amount)
            )
        return

    resource_block = Block()
    set_assignment(resource_block, "type", quoted(building))
    if discovered_amount is not None:
        set_assignment(resource_block, "discovered_amount", scalar(discovered_amount))
    if undiscovered_amount is not None:
        set_assignment(
            resource_block, "undiscovered_amount", scalar(undiscovered_amount)
        )
    append_assignment(state.block, "resource", resource_block)


def remove_value_from_field(
    state: StateRegionDefinition, field: str, value: str
) -> bool:
    target = get_block(state.block, field)
    return remove_scalar_value(target, value) if target is not None else False


def state_script(states: list[StateRegionDefinition]) -> Script:
    return Script([state.assignment for state in states])


def validate_state_regions(states: dict[str, StateRegionDefinition]) -> list[str]:
    errors: list[str] = []
    ids: dict[str, str] = {}
    provinces: dict[str, str] = {}

    for name, state in states.items():
        id_value = assignment_scalar(state.block, "id")
        if id_value is None:
            errors.append(f"{name}: missing id")
        elif id_value.text in ids:
            errors.append(
                f"duplicate state id {id_value.text}: {ids[id_value.text]} and {name}"
            )
        else:
            ids[id_value.text] = name

        province_block = get_block(state.block, "provinces")
        if province_block is None:
            errors.append(f"{name}: missing provinces block")
            continue
        for province in scalar_values(province_block):
            if province in provinces:
                errors.append(
                    f"province {province} occurs in both {provinces[province]} and {name}"
                )
            else:
                provinces[province] = name
    return errors
