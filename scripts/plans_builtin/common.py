from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
import re

from clausewitz import (
    ClausewitzDocument,
    ClausewitzFormatter,
    ClausewitzParser,
    DocumentSchema,
    KeyRule,
)
from clausewitz.nodes import (
    ClausewitzBlock,
    ClausewitzEntry,
    ClausewitzList,
    ClausewitzScalarValue,
)

from plan_api import ApplyResult, EditInfo, ExecutionPlan


def generic_schema() -> DocumentSchema:
    root = KeyRule(name="root", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=True))
    return DocumentSchema(name="generic", root_key="root", root_rule=root)


@dataclass(frozen=True)
class EditRule:
    name: str
    description: str
    predicate: Callable[[tuple[str, ...], ClausewitzEntry, ClausewitzBlock | None], bool]
    apply: Callable[[tuple[str, ...], ClausewitzEntry, ClausewitzBlock | None, "EditContext"], None]


@dataclass(frozen=True)
class EditPlan:
    name: str
    edits: list[EditRule]


@dataclass(frozen=True)
class TextEditRule:
    name: str
    description: str
    apply: Callable[[str], tuple[str, int]]


@dataclass(frozen=True)
class TextEditPlan:
    name: str
    edits: list[TextEditRule]


@dataclass(frozen=True)
class EditContext:
    factor: float
    wealth_min: int | None = None
    wealth_max: int | None = None
    curve_max: float | None = None
    curve_power: float | None = None
    pm_output_multiplier: dict[str, float] | None = None
    pm_tech_threshold: float | None = None
    pm_high_threshold: float | None = None
    pm_tech_output_mult: float | None = None
    pm_high_output_mult: float | None = None


def iter_entries(
    block: ClausewitzBlock, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], ClausewitzEntry, ClausewitzBlock]]:
    for entry in block.entries:
        key = str(entry.key)
        current_path = path + (key,)
        yield current_path, entry, block
        if isinstance(entry.value, ClausewitzBlock):
            yield from iter_entries(entry.value, current_path)
        elif isinstance(entry.value, ClausewitzList):
            for item in entry.value.values:
                if isinstance(item, ClausewitzBlock):
                    yield from iter_entries(item, current_path)


def apply_edits(document: ClausewitzDocument, plan: EditPlan, context: EditContext) -> dict[str, int]:
    counts = {edit.name: 0 for edit in plan.edits}
    for path, entry, parent in iter_entries(document.root):
        for edit in plan.edits:
            if edit.predicate(path, entry, parent):
                counts[edit.name] += 1
                edit.apply(path, entry, parent, context)
    return counts


def apply_text_edits(text: str, plan: TextEditPlan) -> tuple[str, dict[str, int]]:
    counts = {edit.name: 0 for edit in plan.edits}
    updated = text
    for edit in plan.edits:
        updated, count = edit.apply(updated)
        counts[edit.name] += count
    return updated, counts


def format_document(document: ClausewitzDocument, *, preserve: bool = True) -> str:
    formatter = ClausewitzFormatter(mode="preserve" if preserve else "format")
    return formatter.format_document(document)


def edit_infos(edits: list[EditRule] | list[TextEditRule]) -> list[EditInfo]:
    return [EditInfo(name=edit.name, description=edit.description) for edit in edits]


def make_ast_execution_plan(
    name: str,
    plan: EditPlan,
    *,
    describe: Callable[[dict], str],
    context_builder: Callable[[ClausewitzDocument], EditContext],
) -> ExecutionPlan:
    def apply_text(text: str, _path: Path, preserve: bool) -> ApplyResult:
        document = ClausewitzParser(text, generic_schema()).parse_document()
        context = context_builder(document)
        counts = apply_edits(document, plan, context)
        total = sum(counts.values())
        updated_text = format_document(document, preserve=preserve) if total > 0 else None
        return ApplyResult(updated_text=updated_text, counts=counts)

    return ExecutionPlan(
        name=name,
        edits=edit_infos(plan.edits),
        describe=describe,
        apply_text=apply_text,
    )


def make_text_execution_plan(
    name: str,
    plan: TextEditPlan,
    *,
    describe: Callable[[dict], str],
) -> ExecutionPlan:
    def apply_text(text: str, _path: Path, _preserve: bool) -> ApplyResult:
        updated, counts = apply_text_edits(text, plan)
        total = sum(counts.values())
        updated_text = updated if total > 0 else None
        return ApplyResult(updated_text=updated_text, counts=counts)

    return ExecutionPlan(
        name=name,
        edits=edit_infos(plan.edits),
        describe=describe,
        apply_text=apply_text,
    )


def in_building_level_scaled(path: tuple[str, ...]) -> bool:
    return len(path) >= 3 and path[-3] == "building_modifiers" and path[-2] == "level_scaled"


def block_has_key(block: ClausewitzBlock, key: str) -> bool:
    return any(entry.key == key for entry in block.entries)


def find_child_block(block: ClausewitzBlock, key: str) -> ClausewitzBlock | None:
    for entry in block.entries:
        if entry.key == key and isinstance(entry.value, ClausewitzBlock):
            return entry.value
    return None


def find_level_scaled_block(pm_block: ClausewitzBlock) -> ClausewitzBlock | None:
    modifiers = find_child_block(pm_block, "building_modifiers")
    if modifiers is None:
        return None
    return find_child_block(modifiers, "level_scaled")


def find_unscaled_block(pm_block: ClausewitzBlock) -> ClausewitzBlock | None:
    modifiers = find_child_block(pm_block, "building_modifiers")
    if modifiers is None:
        return None
    return find_child_block(modifiers, "unscaled")


def find_professional_services_value(level_scaled: ClausewitzBlock) -> float | None:
    for entry in level_scaled.entries:
        if entry.key == "goods_input_professional_services_add":
            if isinstance(entry.value, ClausewitzScalarValue) and isinstance(entry.value.value, (int, float)):
                return float(entry.value.value)
    return None


def infer_leading_trivia(block: ClausewitzBlock) -> str:
    if block.entries:
        trivia = block.entries[-1].leading_trivia
        if trivia:
            return trivia
    return "\t"


def infer_trailing_trivia(block: ClausewitzBlock) -> str:
    if block.entries:
        trivia = block.entries[-1].trailing_trivia
        if trivia:
            return trivia
    return "\n"


def add_block_entry(block: ClausewitzBlock, key: str, value: ClausewitzScalarValue) -> None:
    block.add_entry(
        key,
        value,
        leading_trivia=infer_leading_trivia(block),
        trailing_trivia=infer_trailing_trivia(block),
        key_trivia=" ",
        operator_trivia=" ",
    )


def format_scaled_value(original: str, scaled: float) -> str:
    if "." not in original and "e" not in original and "E" not in original:
        if scaled.is_integer():
            return str(int(scaled))
    return str(scaled)


def scale_key_value_text(text: str, key: str, factor: float) -> tuple[str, int]:
    pattern = re.compile(rf"(\b{re.escape(key)}\s*=\s*)(-?\d+(?:\.\d+)?)")

    def repl(match: re.Match[str]) -> str:
        raw_value = match.group(2)
        scaled = float(raw_value) * factor
        return match.group(1) + format_scaled_value(raw_value, scaled)

    return pattern.subn(repl, text)


def parse_wealth_level(key: str) -> int | None:
    match = re.fullmatch(r"wealth_(\d+)", key)
    if match is None:
        return None
    return int(match.group(1))


def find_wealth_range(document: ClausewitzDocument) -> tuple[int | None, int | None]:
    wealth_values: list[int] = []
    for entry in document.root.entries:
        key = str(entry.key)
        wealth_level = parse_wealth_level(key)
        if wealth_level is not None:
            wealth_values.append(wealth_level)
    if not wealth_values:
        return None, None
    return min(wealth_values), max(wealth_values)
