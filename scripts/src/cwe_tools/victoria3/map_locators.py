from __future__ import annotations

from dataclasses import dataclass

from cwe_tools.paradox.script.ast import Assignment, Block, Scalar, Script, ValueEntry
from cwe_tools.paradox.script.edit import (
    find_assignment,
    get_block,
    scalar,
    set_assignment,
)


@dataclass(frozen=True)
class Locator:
    id: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


def _vector(values: tuple[float, ...]) -> Block:
    return Block([ValueEntry(scalar(value)) for value in values])


def locator_root(script: Script) -> Block:
    for entry in script.entries:
        if (
            isinstance(entry, Assignment)
            and entry.key == "game_object_locator"
            and isinstance(entry.value, Block)
        ):
            return entry.value

    raise KeyError("Missing game_object_locator block")


def instances_block(script: Script) -> Block:
    root = locator_root(script)
    instances = get_block(root, "instances")
    if instances is None:
        instances = Block()
        set_assignment(root, "instances", instances)
    return instances


def _locator_id(block: Block) -> int | None:
    assignment = find_assignment(block, "id")
    if assignment is None or not isinstance(assignment.value, Scalar):
        return None
    try:
        return int(assignment.value.text)
    except ValueError:
        return None


def set_locator(script: Script, locator: Locator) -> None:
    instances = instances_block(script)
    target: Block | None = None

    for entry in instances.entries:
        if (
            isinstance(entry, ValueEntry)
            and isinstance(entry.value, Block)
            and _locator_id(entry.value) == locator.id
        ):
            target = entry.value
            break

    if target is None:
        target = Block()
        instances.entries.append(ValueEntry(target))

    set_assignment(target, "id", scalar(locator.id))
    set_assignment(target, "position", _vector(locator.position))
    set_assignment(target, "rotation", _vector(locator.rotation))
    set_assignment(target, "scale", _vector(locator.scale))
