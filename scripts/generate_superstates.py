"""Generate the private modern-superstate content from one TOML manifest."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable


BEGIN_MARKER = "# BEGIN GENERATED MODERN SUPERSTATES"
END_MARKER = "# END GENERATED MODERN SUPERSTATES"
POWER_EFFECT_BEGIN = "# BEGIN GENERATED MODERN SUPERSTATE POWER EFFECTS"
POWER_EFFECT_END = "# END GENERATED MODERN SUPERSTATE POWER EFFECTS"
POWER_MODIFIER_BEGIN = "# BEGIN GENERATED MODERN SUPERSTATE POWER MODIFIERS"
POWER_MODIFIER_END = "# END GENERATED MODERN SUPERSTATE POWER MODIFIERS"
TAG_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{2}$")
STATE_PATTERN = re.compile(r"^STATE_[A-Z0-9_]+$")
DEBUG_SEED_STATE_OVERRIDES = {
    # These CWE definitions have blank or stale capital fields, so use stable state regions.
    "BNG": "STATE_EAST_BENGAL",
    "CME": "STATE_SENEGAL",
    "PAU": "STATE_WEST_MICRONESIA",
}


@dataclass(frozen=True)
class CountryDefinition:
    tag: str
    color: tuple[int, int, int]
    capital: str
    cultures: tuple[str, ...]


@dataclass(frozen=True)
class StateRecord:
    name: str
    source_file: str
    owners: frozenset[str]
    claims: frozenset[str]
    homelands: frozenset[str]


@dataclass(frozen=True)
class CoaLayer:
    kind: str
    texture: str
    colors: tuple[str, ...] = ()
    scale: tuple[float, float] = (1.0, 1.0)
    position: tuple[float, float] = (0.5, 0.5)


@dataclass(frozen=True)
class NumericModifier:
    key: str
    raw_value: str
    value: Decimal


@dataclass(frozen=True)
class PowerModifier:
    key: str
    label: str
    rank: str
    score: int
    icon: str
    chassis: tuple[NumericModifier, ...]
    specializations: tuple[NumericModifier, ...]


@dataclass(frozen=True)
class SuperstatePower:
    source_keys: tuple[str, ...]
    strongest: PowerModifier
    specializations: tuple[NumericModifier, ...]


@dataclass
class Superstate:
    tag: str
    name: str
    adjective: str
    founders: list[str]
    definition_founder: str
    history_files: list[str]
    territory_tags: list[str]
    members: list[str]
    flag_pattern: str
    flag_colors: list[tuple[int, int, int]]
    flag_layers: list[CoaLayer]
    flag_script: str
    exclude_states: set[str] = field(default_factory=set)
    include_states: set[str] = field(default_factory=set)
    subtract: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)


class ValidationError(RuntimeError):
    """Raised when manifest or generated content is inconsistent."""


def strip_comments(text: str) -> str:
    return re.sub(r"(?m)#.*$", "", text)


def remove_generated_block(text: str) -> str:
    if BEGIN_MARKER not in text and END_MARKER not in text:
        return text
    if text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValidationError("Generated block markers are inconsistent")
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER) + len(END_MARKER)
    return f"{text[:start]}{text[end:]}"


def matching_brace_index(text: str, open_brace: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_brace, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValidationError("Unbalanced braces while parsing Jomini content")


def extract_braced_block(text: str, open_brace: int) -> str:
    return text[open_brace + 1 : matching_brace_index(text, open_brace)]


def remove_named_generated_block(text: str, begin: str, end: str) -> str:
    if begin not in text and end not in text:
        return text
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValidationError(f"Generated block markers are inconsistent: {begin}")
    start = text.index(begin)
    finish = text.index(end) + len(end)
    return f"{text[:start]}{text[finish:]}"


def named_blocks(text: str, pattern: re.Pattern[str]) -> Iterable[tuple[str, str]]:
    for match in pattern.finditer(text):
        open_brace = text.find("{", match.start(), match.end() + 2)
        if open_brace < 0:
            raise ValidationError(f"Missing opening brace after {match.group(1)}")
        yield match.group(1), extract_braced_block(text, open_brace)


def parse_country_definitions(directory: Path) -> dict[str, CountryDefinition]:
    definitions: dict[str, CountryDefinition] = {}
    block_pattern = re.compile(r"(?m)^([A-Z][A-Z0-9]{2})\s*=\s*\{")
    for path in sorted(directory.glob("*.txt")):
        text = remove_generated_block(path.read_text(encoding="utf-8-sig", errors="strict"))
        text = strip_comments(text)
        for tag, body in named_blocks(text, block_pattern):
            color_match = re.search(r"\bcolor\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}", body)
            capital_match = re.search(r"\bcapital\s*=\s*(STATE_[A-Z0-9_]+)", body)
            cultures_match = re.search(r"\bcultures\s*=\s*\{([^}]*)\}", body, re.S)
            definitions[tag] = CountryDefinition(
                tag=tag,
                color=(
                    tuple(int(value) for value in color_match.groups())
                    if color_match
                    else (0, 0, 0)
                ),
                capital=capital_match.group(1) if capital_match else "",
                cultures=(
                    tuple(re.findall(r"[a-z][a-z0-9_]*", cultures_match.group(1)))
                    if cultures_match
                    else ()
                ),
            )
    return definitions


def parse_state_history(directory: Path) -> dict[str, StateRecord]:
    records: dict[str, StateRecord] = {}
    block_pattern = re.compile(r"(?m)^\s*s:(STATE_[A-Z0-9_]+)\s*=\s*\{")
    for path in sorted(directory.glob("*.txt")):
        text = strip_comments(path.read_text(encoding="utf-8-sig", errors="strict"))
        for state, body in named_blocks(text, block_pattern):
            if state in records:
                raise ValidationError(f"State {state} occurs in more than one history file")
            records[state] = StateRecord(
                name=state,
                source_file=path.name,
                owners=frozenset(re.findall(r"\bcountry\s*=\s*c:([A-Z0-9]{3})", body)),
                claims=frozenset(re.findall(r"\badd_claim\s*=\s*c:([A-Z0-9]{3})", body)),
                homelands=frozenset(re.findall(r"\badd_homeland\s*=\s*cu:([a-z0-9_]+)", body)),
            )
    return records


def parse_numeric_modifiers(text: str) -> tuple[NumericModifier, ...]:
    pattern = re.compile(
        r"(?m)^\s*([a-z][a-z0-9_]+)\s*=\s*(-?\d+(?:\.\d+)?)\s*$"
    )
    return tuple(
        NumericModifier(key=match.group(1), raw_value=match.group(2), value=Decimal(match.group(2)))
        for match in pattern.finditer(text)
    )


def parse_power_modifiers(text: str) -> dict[str, PowerModifier]:
    text = remove_named_generated_block(text, POWER_MODIFIER_BEGIN, POWER_MODIFIER_END)
    header_pattern = re.compile(
        r"(?m)^###\s+(.+?)\s+\|\s+rank=([^|]+?)\s+\|\s+score=(\d+)\s*\r?\n"
        r"(modern_country_power_[a-z0-9_]+)\s*=\s*\{"
    )
    modifiers: dict[str, PowerModifier] = {}
    for match in header_pattern.finditer(text):
        open_brace = text.find("{", match.start(4), match.end())
        body = extract_braced_block(text, open_brace)
        icon_match = re.search(r"(?m)^\s*icon\s*=\s*([^\s#]+)", body)
        universal_match = re.search(
            r"(?mi)^\s*#.*universal national chassis\s*$", body
        )
        primary_match = re.search(
            r"(?mi)^\s*#\s*primary strategic industries\s*$", body
        )
        if not icon_match or not universal_match or not primary_match:
            raise ValidationError(f"Could not parse country-power sections for {match.group(4)}")
        chassis = parse_numeric_modifiers(body[universal_match.end() : primary_match.start()])
        specializations = parse_numeric_modifiers(body[primary_match.end() :])
        if not chassis:
            raise ValidationError(f"Country-power modifier {match.group(4)} has no national chassis")
        if not any(entry.key == "state_birth_rate_mult" for entry in chassis):
            raise ValidationError(f"Country-power modifier {match.group(4)} has no birth-rate chassis value")
        modifiers[match.group(4)] = PowerModifier(
            key=match.group(4),
            label=match.group(1),
            rank=match.group(2).strip(),
            score=int(match.group(3)),
            icon=icon_match.group(1),
            chassis=chassis,
            specializations=specializations,
        )
    if not modifiers:
        raise ValidationError("No country-power modifiers were parsed")
    return modifiers


def parse_power_tag_map(text: str) -> dict[str, str]:
    text = remove_named_generated_block(text, POWER_EFFECT_BEGIN, POWER_EFFECT_END)
    pair_pattern = re.compile(
        r"\blimit\s*=\s*\{\s*exists\s*=\s*c:([A-Z0-9]{3})\s*\}"
        r".*?\badd_modifier\s*=\s*\{\s*name\s*=\s*(modern_country_power_[a-z0-9_]+)",
        re.S,
    )
    mapping: dict[str, str] = {}
    for tag, modifier in pair_pattern.findall(text):
        previous = mapping.get(tag)
        if previous and previous != modifier:
            raise ValidationError(f"Country tag {tag} maps to conflicting power modifiers")
        mapping[tag] = modifier
    if not mapping:
        raise ValidationError("No country-to-power-modifier assignments were parsed")
    return mapping


def stronger_specialization(
    current: NumericModifier, candidate: NumericModifier
) -> NumericModifier:
    if current.value < 0 and candidate.value < 0:
        return candidate if candidate.value < current.value else current
    return candidate if candidate.value > current.value else current


def build_superstate_powers(
    superstates: list[Superstate],
    tag_map: dict[str, str],
    modifiers: dict[str, PowerModifier],
) -> dict[str, SuperstatePower]:
    result: dict[str, SuperstatePower] = {}
    for item in superstates:
        candidate_tags = list(dict.fromkeys(item.founders + item.territory_tags + item.members))
        source_keys = tuple(
            dict.fromkeys(tag_map[tag] for tag in candidate_tags if tag in tag_map)
        )
        if not source_keys:
            raise ValidationError(f"{item.tag} has no constituent country-power modifiers")
        missing = sorted(set(source_keys) - set(modifiers))
        if missing:
            raise ValidationError(
                f"{item.tag} references undefined country-power modifiers: {', '.join(missing)}"
            )
        sources = [modifiers[key] for key in source_keys]
        strongest = max(sources, key=lambda source: source.score)
        merged: dict[str, NumericModifier] = {}
        for source in sources:
            for entry in source.specializations:
                merged[entry.key] = (
                    stronger_specialization(merged[entry.key], entry)
                    if entry.key in merged
                    else entry
                )
        result[item.tag] = SuperstatePower(
            source_keys=source_keys,
            strongest=strongest,
            specializations=tuple(merged[key] for key in sorted(merged)),
        )
    return result


def validate_law_effects(superstates: list[Superstate], text: str) -> None:
    effect_pattern = re.compile(r"(?m)^(effect_[a-z0-9_]+_laws)\s*=\s*\{")
    effects: dict[str, str] = {}
    for match in effect_pattern.finditer(text):
        open_brace = text.find("{", match.start(), match.end())
        effects[match.group(1)] = extract_braced_block(text, open_brace)
    missing = sorted(
        superstate_law_effect_key(item)
        for item in superstates
        if superstate_law_effect_key(item) not in effects
    )
    if missing:
        raise ValidationError(f"Missing superstate law effects: {', '.join(missing)}")
    empty = sorted(
        key for key, body in effects.items()
        if key in {superstate_law_effect_key(item) for item in superstates}
        and "activate_law" not in body
    )
    if empty:
        raise ValidationError(f"Superstate law effects have no laws: {', '.join(empty)}")


def load_manifest(path: Path) -> list[Superstate]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValidationError("Unsupported modern-superstate manifest version")
    result: list[Superstate] = []
    for item in raw.get("superstate", []):
        result.append(
            Superstate(
                tag=item["tag"],
                name=item["name"],
                adjective=item["adjective"],
                founders=list(item["founders"]),
                definition_founder=item["definition_founder"],
                history_files=list(item["history_files"]),
                territory_tags=list(item["territory_tags"]),
                members=list(item["members"]),
                flag_pattern=item.get("flag_pattern", ""),
                flag_colors=[tuple(color) for color in item.get("flag_colors", [])],
                flag_layers=[
                    CoaLayer(
                        kind=layer["kind"],
                        texture=layer["texture"],
                        colors=tuple(layer.get("colors", [])),
                        scale=tuple(layer.get("scale", [1.0, 1.0])),
                        position=tuple(layer.get("position", [0.5, 0.5])),
                    )
                    for layer in item.get("flag_layers", [])
                ],
                flag_script=item.get("flag_script", "").strip("\r\n"),
                exclude_states=set(item.get("exclude_states", [])),
                include_states=set(item.get("include_states", [])),
                subtract=list(item.get("subtract", [])),
            )
        )
    return result


def validate_manifest(
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    states: dict[str, StateRecord],
    history_directory: Path,
) -> None:
    tags = [item.tag for item in superstates]
    duplicate_tags = sorted({tag for tag in tags if tags.count(tag) > 1})
    if duplicate_tags:
        raise ValidationError(f"Duplicate generated tags: {', '.join(duplicate_tags)}")
    collisions = sorted(set(tags) & set(definitions))
    if collisions:
        raise ValidationError(f"Generated tags already exist: {', '.join(collisions)}")

    known_superstates = set(tags)
    for item in superstates:
        if not TAG_PATTERN.fullmatch(item.tag):
            raise ValidationError(f"Invalid generated tag: {item.tag}")
        if not item.tag.startswith("Z"):
            raise ValidationError(f"Generated tag must use the Z namespace: {item.tag}")
        referenced_tags = set(item.founders + [item.definition_founder] + item.territory_tags + item.members)
        unknown_tags = sorted(referenced_tags - set(definitions))
        if unknown_tags:
            raise ValidationError(f"{item.tag} references unknown country tags: {', '.join(unknown_tags)}")
        founder_definition = definitions[item.definition_founder]
        if not founder_definition.capital or not founder_definition.cultures:
            raise ValidationError(
                f"{item.tag} definition founder {item.definition_founder} lacks a capital or cultures"
            )
        unknown_files = sorted(
            filename for filename in item.history_files if not (history_directory / filename).is_file()
        )
        if unknown_files:
            raise ValidationError(f"{item.tag} references missing history files: {', '.join(unknown_files)}")
        unknown_states = sorted((item.include_states | item.exclude_states) - set(states))
        if unknown_states:
            raise ValidationError(f"{item.tag} references unknown states: {', '.join(unknown_states)}")
        unknown_subtractions = sorted(set(item.subtract) - known_superstates)
        if unknown_subtractions:
            raise ValidationError(
                f"{item.tag} subtracts unknown superstates: {', '.join(unknown_subtractions)}"
            )
        if item.flag_script:
            if item.flag_pattern or item.flag_colors or item.flag_layers:
                raise ValidationError(
                    f"{item.tag} cannot combine flag_script with structured flag fields"
                )
            validate_braces(Path(f"manifest:{item.tag}:flag_script"), f"{{{item.flag_script}}}")
            continue
        if not 1 <= len(item.flag_colors) <= 3:
            raise ValidationError(f"{item.tag} must define between one and three flag colors")
        for color in item.flag_colors:
            if len(color) != 3 or any(
                not isinstance(channel, int) or not 0 <= channel <= 255 for channel in color
            ):
                raise ValidationError(f"{item.tag} has an invalid RGB flag color: {color}")
        if not item.flag_layers:
            raise ValidationError(f"{item.tag} must define at least one flag layer")
        for layer in item.flag_layers:
            if layer.kind not in {"colored", "textured"}:
                raise ValidationError(f"{item.tag} has invalid flag layer kind: {layer.kind}")
            if layer.kind == "colored" and not 1 <= len(layer.colors) <= 3:
                raise ValidationError(
                    f"{item.tag} colored layer {layer.texture} needs one to three colors"
                )
            if layer.kind == "textured" and layer.colors:
                raise ValidationError(
                    f"{item.tag} textured layer {layer.texture} cannot define colors"
                )
            for color in layer.colors:
                match = re.fullmatch(r"color([123])", color)
                if match and int(match.group(1)) > len(item.flag_colors):
                    raise ValidationError(
                        f"{item.tag} layer {layer.texture} references missing {color}"
                    )
            if len(layer.scale) != 2 or any(value <= 0 or value > 2 for value in layer.scale):
                raise ValidationError(
                    f"{item.tag} has invalid scale for {layer.texture}: {layer.scale}"
                )
            if len(layer.position) != 2 or any(value < 0 or value > 1 for value in layer.position):
                raise ValidationError(
                    f"{item.tag} has invalid position for {layer.texture}: {layer.position}"
                )


def derive_states(superstates: list[Superstate], records: dict[str, StateRecord]) -> None:
    resolved: dict[str, set[str]] = {}
    for item in superstates:
        allowed_files = set(item.history_files)
        territory_tags = set(item.territory_tags)
        selected = {
            name
            for name, record in records.items()
            if record.source_file in allowed_files
            and ((record.owners | record.claims) & territory_tags)
        }
        selected |= item.include_states
        selected -= item.exclude_states
        for dependency in item.subtract:
            if dependency not in resolved:
                raise ValidationError(f"{item.tag} subtracts {dependency} before it has been resolved")
            selected -= resolved[dependency]
        if not selected:
            raise ValidationError(f"{item.tag} has no derived states")
        item.states = sorted(selected)
        resolved[item.tag] = selected

    owners: dict[str, list[str]] = {}
    for item in superstates:
        for state in item.states:
            owners.setdefault(state, []).append(item.tag)
    overlaps = {state: tags for state, tags in owners.items() if len(tags) > 1}
    if overlaps:
        details = "; ".join(f"{state}={','.join(tags)}" for state, tags in sorted(overlaps.items()))
        raise ValidationError(f"Canonical state lists overlap: {details}")


def validate_assets(superstates: list[Superstate], game_root: Path, mod_root: Path) -> None:
    roots = [game_root / "gfx" / "coat_of_arms", mod_root / "gfx" / "coat_of_arms"]
    available = {path.name for root in roots if root.is_dir() for path in root.rglob("*") if path.is_file()}
    required = {
        asset
        for item in superstates
        for asset in [item.flag_pattern, *(layer.texture for layer in item.flag_layers)]
        if asset
    }
    required.update(
        asset
        for item in superstates
        for asset in re.findall(
            r'\b(?:pattern|texture)\s*=\s*"([^"]+)"', item.flag_script
        )
    )
    missing = sorted(required - available)
    if missing:
        raise ValidationError(f"Missing COA textures: {', '.join(missing)}")


def definition_cultures(
    item: Superstate,
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> list[str]:
    cultures = {culture for state in item.states for culture in records[state].homelands}
    if not cultures:
        cultures.update(definitions[item.definition_founder].cultures)
    return sorted(cultures)


def additional_primary_cultures(
    item: Superstate,
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> list[str]:
    founder_cultures = set(definitions[item.definition_founder].cultures)
    return [
        culture
        for culture in definition_cultures(item, definitions, records)
        if culture not in founder_cultures
    ]


def wrap_tokens(tokens: list[str], indent: str, width: int = 110) -> list[str]:
    lines: list[str] = []
    current = indent
    for token in tokens:
        candidate = f"{current} {token}" if current.strip() else f"{indent}{token}"
        if current.strip() and len(candidate) > width:
            lines.append(current)
            current = f"{indent}{token}"
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def generated_block(body: str) -> str:
    return f"{BEGIN_MARKER}\n{body.rstrip()}\n{END_MARKER}"


def merge_generated_block(existing: str, body: str) -> str:
    block = generated_block(body)
    if BEGIN_MARKER in existing or END_MARKER in existing:
        if existing.count(BEGIN_MARKER) != 1 or existing.count(END_MARKER) != 1:
            raise ValidationError("Generated block markers are inconsistent")
        start = existing.index(BEGIN_MARKER)
        end = existing.index(END_MARKER) + len(END_MARKER)
        return f"{existing[:start].rstrip()}\n\n{block}{existing[end:].rstrip()}\n"
    return f"{existing.rstrip()}\n\n{block}\n"


def merge_appended_generated_block(
    existing: str, body: str, begin: str, end: str
) -> str:
    cleaned = remove_named_generated_block(existing, begin, end).rstrip()
    return f"{cleaned}\n\n{begin}\n{body.rstrip()}\n{end}\n"


def merge_generated_inside_effect(
    existing: str, effect_name: str, body: str, begin: str, end: str
) -> str:
    cleaned = remove_named_generated_block(existing, begin, end)
    match = re.search(rf"(?m)^{re.escape(effect_name)}\s*=\s*\{{", cleaned)
    if not match:
        raise ValidationError(f"Could not find scripted effect {effect_name}")
    open_brace = cleaned.find("{", match.start(), match.end())
    close_brace = matching_brace_index(cleaned, open_brace)
    indented_body = "\n".join(f"\t{line}" if line else "" for line in body.rstrip().splitlines())
    insertion = f"\n\t{begin}\n{indented_body}\n\t{end}\n"
    return f"{cleaned[:close_brace].rstrip()}{insertion}{cleaned[close_brace:]}"


def render_definitions(
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> str:
    blocks: list[str] = []
    for item in superstates:
        founder = definitions[item.definition_founder]
        cultures = " ".join(definition_cultures(item, definitions, records))
        color = " ".join(str(value) for value in founder.color)
        blocks.append(
            f"{item.tag} = {{ # {item.name}\n"
            f"\tcolor = {{ {color} }}\n"
            "\tcountry_type = recognized\n"
            "\ttier = hegemony\n"
            "\tvalid_as_home_country_for_separatists = { always = no }\n"
            f"\tcultures = {{ {cultures} }}\n"
            f"\tcapital = {founder.capital}\n"
            "}"
        )
    return "\n\n".join(blocks)


def render_founder_trigger(founders: list[str], indent: str) -> list[str]:
    if len(founders) == 1:
        return [f"{indent}c:{founders[0]} ?= this"]
    lines = [f"{indent}OR = {{"]
    lines.extend(f"{indent}\tc:{tag} ?= this" for tag in founders)
    lines.append(f"{indent}}}")
    return lines


def render_formations(superstates: list[Superstate]) -> str:
    blocks: list[str] = []
    for item in superstates:
        lines = [f"{item.tag} = {{ # {item.name}", "\tstates = {"]
        lines.extend(wrap_tokens(item.states, "\t\t"))
        lines.extend(
            [
                "\t}",
                "\trequired_states_fraction = 1.0",
                "\tai_will_do = { always = no }",
                "\tpossible = {",
                "\t\tis_player = yes",
            ]
        )
        lines.extend(render_founder_trigger(item.founders, "\t\t"))
        lines.extend(["\t}", "}"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def superstate_power_key(item: Superstate) -> str:
    return f"modern_country_power_{item.tag.lower()}"


def superstate_law_effect_key(item: Superstate) -> str:
    return f"effect_{item.tag.lower()}_laws"


def render_decisions(
    superstates: list[Superstate],
    powers: dict[str, SuperstatePower],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> str:
    blocks: list[str] = []
    for item in superstates:
        decision_id = f"form_{item.tag.lower()}_decision"
        lines = [
            f"{decision_id} = {{",
            "\tis_shown = {",
            "\t\tis_player = yes",
        ]
        lines.extend(render_founder_trigger(item.founders, "\t\t"))
        lines.extend(
            [
                f"\t\tNOT = {{ exists = c:{item.tag} }}",
                "\t}",
                "\tpossible = { always = yes }",
                "\twhen_taken = {",
                "\t\tsave_scope_as = modern_superstate_founder",
                "\t\tevery_country = {",
                "\t\t\tlimit = {",
                "\t\t\t\tNOT = { THIS = ROOT }",
                "\t\t\t\tOR = {",
            ]
        )
        lines.extend(f"\t\t\t\t\tc:{tag} ?= this" for tag in item.members)
        lines.extend(
            [
                "\t\t\t\t}",
                "\t\t\t}",
                "\t\t\tsave_scope_as = modern_superstate_member",
                "\t\t\tscope:modern_superstate_founder = {",
                "\t\t\t\tannex_with_incorporation = scope:modern_superstate_member",
                "\t\t\t}",
                "\t\t}",
            ]
        )
        lines.extend(
            f"\t\tremove_modifier = {modifier}" for modifier in powers[item.tag].source_keys
        )
        lines.append(f"\t\tchange_tag = {item.tag}")
        lines.extend(
            f"\t\tadd_primary_culture = cu:{culture}"
            for culture in additional_primary_cultures(item, definitions, records)
        )
        lines.extend(
            [
                f"\t\t{superstate_law_effect_key(item)} = yes",
                "\t\tadd_modifier = {",
                f"\t\t\tname = {superstate_power_key(item)}",
                "\t\t\tduration = -1",
                "\t\t}",
                "\t}",
                "\tai_chance = { value = 0 }",
                "}",
            ]
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def debug_release_candidates(
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> list[tuple[str, str]]:
    """Return missing-at-start member tags and deterministic seed state regions."""
    starting_tags = {owner for record in records.values() for owner in record.owners}
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for item in superstates:
        for tag in item.members:
            if tag in seen or tag in starting_tags:
                continue
            seen.add(tag)
            definition = definitions[tag]
            seed_state = definition.capital if definition.capital in records else ""
            if not seed_state:
                seed_state = DEBUG_SEED_STATE_OVERRIDES.get(tag, "")
            if not seed_state:
                seed_state = next(
                    (
                        state
                        for state in item.states
                        if tag in (records[state].owners | records[state].claims)
                    ),
                    "",
                )
            if not seed_state:
                cultures = set(definition.cultures)
                seed_state = next(
                    (
                        state
                        for state in item.states
                        if cultures & records[state].homelands
                    ),
                    "",
                )
            if not seed_state or seed_state not in records:
                raise ValidationError(f"No deterministic debug seed state for {tag}")
            candidates.append((tag, seed_state))
    return candidates


def render_debug_release_effect(
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> str:
    lines = [
        "# Generated debug helper for the private modern-superstate test setup.",
        "# It is intentionally not called by an on_action, decision, journal entry, or scripted button.",
        "# Run debug_release_modern_superstate_test_countries manually in the debug script runner.",
        "debug_release_modern_superstate_test_countries = {",
        "\t# Release every direct subject of the country used as the script-runner ROOT.",
        "\tevery_country = {",
        "\t\tlimit = {",
        "\t\t\tis_subject_of = ROOT",
        "\t\t}",
        "\t\tmake_independent = yes",
        "\t}",
        "",
        "\t# Create relevant constituent tags missing from the 1949 starting setup.",
        "\t# random_scope_state is deterministic here: ROOT has at most one state object per named region.",
    ]
    for tag, seed_state in debug_release_candidates(superstates, definitions, records):
        lines.extend(
            [
                "",
                f"\t# {tag} — {seed_state}",
                "\tif = {",
                "\t\tlimit = {",
                f"\t\t\tNOT = {{ exists = c:{tag} }}",
                "\t\t\tany_scope_state = {",
                f"\t\t\t\tstate_region = s:{seed_state}",
                "\t\t\t}",
                "\t\t}",
                "\t\trandom_scope_state = {",
                "\t\t\tlimit = {",
                f"\t\t\t\tstate_region = s:{seed_state}",
                "\t\t\t}",
                "\t\t\tsave_scope_as = modern_superstate_debug_seed_state",
                "\t\t}",
                "\t\tcreate_country = {",
                f"\t\t\ttag = {tag}",
                "\t\t\torigin = ROOT",
                "\t\t\tstate = scope:modern_superstate_debug_seed_state",
                "\t\t}",
                "\t\tclear_saved_scope = modern_superstate_debug_seed_state",
                "\t}",
            ]
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_localization(superstates: list[Superstate]) -> str:
    lines = ["l_english:"]
    for item in superstates:
        decision_id = f"form_{item.tag.lower()}_decision"
        lines.extend(
            [
                f'  {item.tag}:0 "{item.name}"',
                f'  {item.tag}_ADJ:0 "{item.adjective}"',
                f'  {decision_id}:0 "Form {item.name}"',
                f'  {decision_id}_desc:0 "Unite the configured member countries as {item.name}. Only whole countries that currently exist will be annexed."',
                f'  {superstate_power_key(item)}:0 "{item.name} Integrated Power"',
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_power_modifiers(
    superstates: list[Superstate], powers: dict[str, SuperstatePower]
) -> str:
    blocks: list[str] = []
    for item in superstates:
        power = powers[item.tag]
        lines = [
            f"### {item.name} | strongest={power.strongest.label} | "
            f"rank={power.strongest.rank} | score={power.strongest.score}",
            f"{superstate_power_key(item)} = {{",
            f"\ticon = {power.strongest.icon}",
            "",
            f"\t# Universal national chassis copied from {power.strongest.label}",
        ]
        for entry in power.strongest.chassis:
            value = "0.1" if entry.key == "state_birth_rate_mult" else entry.raw_value
            lines.append(f"\t{entry.key} = {value}")
        lines.extend(
            [
                "",
                "\t# All constituent specializations; strongest value retained per modifier",
            ]
        )
        lines.extend(
            f"\t{entry.key} = {entry.raw_value}"
            for entry in power.specializations
            if entry.key != "state_birth_rate_mult"
        )
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_power_effects(
    superstates: list[Superstate], powers: dict[str, SuperstatePower]
) -> str:
    blocks: list[str] = []
    for item in superstates:
        lines = [
            f"### {item.name}",
            "if = {",
            f"\tlimit = {{ exists = c:{item.tag} }}",
            f"\tc:{item.tag} = {{",
        ]
        lines.extend(
            f"\t\tremove_modifier = {modifier}" for modifier in powers[item.tag].source_keys
        )
        lines.extend(
            [
                "\t\tif = {",
                f"\t\t\tlimit = {{ NOT = {{ has_modifier = {superstate_power_key(item)} }} }}",
                "\t\t\tadd_modifier = {",
                f"\t\t\t\tname = {superstate_power_key(item)}",
                "\t\t\t\tduration = -1",
                "\t\t\t}",
                "\t\t}",
                "\t}",
                "}",
            ]
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_coa_color(color: str) -> str:
    return color if re.fullmatch(r"color[123]", color) else f'"{color}"'


def render_coas(superstates: list[Superstate]) -> str:
    blocks: list[str] = []
    for item in superstates:
        if item.flag_script:
            blocks.append(f"{item.tag} = {{ # {item.name}\n{item.flag_script.rstrip()}\n}}")
            continue
        lines = [
            f"{item.tag} = {{ # {item.name}",
            f'\tpattern = "{item.flag_pattern}"',
        ]
        lines.extend(
            f"\tcolor{index} = {{ {' '.join(str(channel) for channel in color)} }}"
            for index, color in enumerate(item.flag_colors, start=1)
        )
        for layer in item.flag_layers:
            emblem_type = "colored_emblem" if layer.kind == "colored" else "textured_emblem"
            lines.extend(["", f"\t{emblem_type} = {{", f'\t\ttexture = "{layer.texture}"'])
            lines.extend(
                f"\t\tcolor{index} = {render_coa_color(color)}"
                for index, color in enumerate(layer.colors, start=1)
            )
            scale = " ".join(f"{value:g}" for value in layer.scale)
            position = " ".join(f"{value:g}" for value in layer.position)
            lines.extend(
                [
                    f"\t\tinstance = {{ scale = {{ {scale} }} position = {{ {position} }} }}",
                    "\t}",
                ]
            )
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_report(
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
    powers: dict[str, SuperstatePower],
) -> str:
    lines = [
        "# Modern Superstate Generation Report",
        "",
        "Generated from `scripts/manifests/modern_superstates.toml`.",
        "",
    ]
    for item in superstates:
        lines.extend(
            [
                f"## {item.tag} — {item.name}",
                "",
                f"- Founders: {', '.join(item.founders)}",
                f"- Whole-country annex list: {', '.join(item.members)}",
                f"- Canonical states: {len(item.states)}",
                f"- Power chassis: {powers[item.tag].strongest.label} "
                f"(rank {powers[item.tag].strongest.rank}, score {powers[item.tag].strongest.score})",
                f"- Merged country-power modifiers: {', '.join(powers[item.tag].source_keys)}",
                f"- Merged specialization keys: {len(powers[item.tag].specializations)}",
                f"- Formation law package: {superstate_law_effect_key(item)}",
                f"- Primary cultures added on formation: "
                f"{', '.join(additional_primary_cultures(item, definitions, records)) or 'none'}",
                "",
                "| State | History file | Matching owners/claims |",
                "|---|---|---|",
            ]
        )
        territory_tags = set(item.territory_tags)
        for state in item.states:
            record = records[state]
            matches = sorted((record.owners | record.claims) & territory_tags)
            lines.append(f"| {state} | {record.source_file} | {', '.join(matches) or 'explicit include'} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def expected_outputs(
    root: Path,
    superstates: list[Superstate],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
    powers: dict[str, SuperstatePower],
    power_effect_source: str,
    power_modifier_source: str,
) -> dict[Path, tuple[str, str]]:
    definition_path = root / "common" / "country_definitions" / "00_modern_countries.txt"
    formation_path = root / "common" / "country_formation" / "modern_formables.txt"
    merged_definitions = merge_generated_block(
        definition_path.read_text(encoding="utf-8-sig"),
        render_definitions(superstates, definitions, records),
    )
    merged_formations = merge_generated_block(
        formation_path.read_text(encoding="utf-8-sig"), render_formations(superstates)
    )
    merged_power_effects = merge_generated_inside_effect(
        power_effect_source,
        "modern_apply_country_power_modifiers",
        render_power_effects(superstates, powers),
        POWER_EFFECT_BEGIN,
        POWER_EFFECT_END,
    )
    merged_power_modifiers = merge_appended_generated_block(
        power_modifier_source,
        render_power_modifiers(superstates, powers),
        POWER_MODIFIER_BEGIN,
        POWER_MODIFIER_END,
    )
    effect_path = root / "common" / "scripted_effects" / "modern_country_power_effects.txt"
    modifier_path = root / "common" / "static_modifiers" / "modern_country_power_modifiers.txt"
    effect_encoding = "utf-8-sig" if effect_path.read_bytes().startswith(b"\xef\xbb\xbf") else "utf-8"
    modifier_encoding = "utf-8-sig" if modifier_path.read_bytes().startswith(b"\xef\xbb\xbf") else "utf-8"
    return {
        definition_path: (merged_definitions, "utf-8"),
        formation_path: (merged_formations, "utf-8"),
        root / "common" / "decisions" / "modern_superstate_decisions.txt": (
            render_decisions(superstates, powers, definitions, records),
            "utf-8",
        ),
        root / "common" / "scripted_effects" / "modern_superstate_debug_effects.txt": (
            render_debug_release_effect(superstates, definitions, records),
            "utf-8",
        ),
        root / "localization" / "english" / "0_modern_countries_l_english.yml": (
            render_localization(superstates),
            "utf-8-sig",
        ),
        root / "common" / "coat_of_arms" / "coat_of_arms" / "00_modern_superstate_coas.txt": (
            render_coas(superstates),
            "utf-8",
        ),
        root / "scripts" / "validation" / "modern_superstates_report.md": (
            render_report(superstates, definitions, records, powers),
            "utf-8",
        ),
        effect_path: (merged_power_effects, effect_encoding),
        modifier_path: (merged_power_modifiers, modifier_encoding),
    }


def write_outputs(outputs: dict[Path, tuple[str, str]]) -> None:
    for path, (content, encoding) in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding, newline="\n")
        print(f"wrote {path}")


def check_outputs(outputs: dict[Path, tuple[str, str]]) -> None:
    stale: list[str] = []
    for path, (expected, encoding) in outputs.items():
        if not path.is_file():
            stale.append(f"missing: {path}")
            continue
        actual = path.read_text(encoding=encoding)
        if actual != expected:
            stale.append(f"stale: {path}")
    if stale:
        raise ValidationError("Generated outputs are not current:\n" + "\n".join(stale))
    print(f"validated {len(outputs)} generated outputs")


def validate_braces(path: Path, text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in strip_comments(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValidationError(f"Closing brace without opener in {path}")
    if depth != 0 or in_string:
        raise ValidationError(f"Unbalanced braces or quotes in {path}")


def validate_rendered_outputs(
    outputs: dict[Path, tuple[str, str]],
    superstates: list[Superstate],
    powers: dict[str, SuperstatePower],
    definitions: dict[str, CountryDefinition],
    records: dict[str, StateRecord],
) -> None:
    for path, (content, _) in outputs.items():
        if path.suffix == ".txt":
            validate_braces(path, content)

    localization_path = next(path for path in outputs if path.suffix == ".yml")
    localization = outputs[localization_path][0]
    keys = re.findall(r"(?m)^\s{2}([A-Za-z0-9_]+):0\s", localization)
    duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
    if duplicate_keys:
        raise ValidationError(f"Duplicate localization keys: {', '.join(duplicate_keys)}")

    expected_keys = {
        key
        for item in superstates
        for key in (
            item.tag,
            f"{item.tag}_ADJ",
            f"form_{item.tag.lower()}_decision",
            f"form_{item.tag.lower()}_decision_desc",
            superstate_power_key(item),
        )
    }
    if set(keys) != expected_keys:
        missing = sorted(expected_keys - set(keys))
        extra = sorted(set(keys) - expected_keys)
        raise ValidationError(
            f"Localization key mismatch; missing={missing or 'none'}, extra={extra or 'none'}"
        )

    decision_path = next(path for path in outputs if path.name == "modern_superstate_decisions.txt")
    decision_count = len(re.findall(r"(?m)^form_[a-z0-9]+_decision\s*=\s*\{", outputs[decision_path][0]))
    if decision_count != len(superstates):
        raise ValidationError(
            f"Expected {len(superstates)} generated decisions, found {decision_count}"
        )

    decision_text = outputs[decision_path][0]
    debug_effect_path = next(
        path for path in outputs if path.name == "modern_superstate_debug_effects.txt"
    )
    debug_effect_text = outputs[debug_effect_path][0]
    debug_candidates = debug_release_candidates(superstates, definitions, records)
    if debug_effect_text.count("make_independent = yes") != 1:
        raise ValidationError("Debug release effect must release ROOT's direct subjects exactly once")
    if debug_effect_text.count("create_country = {") != len(debug_candidates):
        raise ValidationError("Debug release effect has the wrong number of country-creation blocks")
    for tag, seed_state in debug_candidates:
        if (
            f"NOT = {{ exists = c:{tag} }}" not in debug_effect_text
            or f"tag = {tag}" not in debug_effect_text
            or f"state_region = s:{seed_state}" not in debug_effect_text
        ):
            raise ValidationError(f"Debug release effect is missing deterministic release data for {tag}")
    modifier_path = next(
        path for path in outputs if path.name == "modern_country_power_modifiers.txt"
    )
    modifier_text = outputs[modifier_path][0]
    effect_path = next(
        path for path in outputs if path.name == "modern_country_power_effects.txt"
    )
    effect_text = outputs[effect_path][0]
    for item in superstates:
        power_key = superstate_power_key(item)
        modifier_match = re.search(rf"(?m)^{re.escape(power_key)}\s*=\s*\{{", modifier_text)
        if not modifier_match:
            raise ValidationError(f"Missing rendered power modifier {power_key}")
        modifier_open = modifier_text.find("{", modifier_match.start(), modifier_match.end())
        modifier_body = extract_braced_block(modifier_text, modifier_open)
        assignments = parse_numeric_modifiers(modifier_body)
        assignment_keys = [entry.key for entry in assignments]
        duplicate_assignments = sorted(
            {key for key in assignment_keys if assignment_keys.count(key) > 1}
        )
        if duplicate_assignments:
            raise ValidationError(
                f"{power_key} stacks duplicate modifiers: {', '.join(duplicate_assignments)}"
            )
        birth_rates = [
            entry for entry in assignments if entry.key == "state_birth_rate_mult"
        ]
        if len(birth_rates) != 1 or birth_rates[0].value != Decimal("0.1"):
            raise ValidationError(f"{power_key} must have exactly 0.1 birth-rate bonus")
        expected_specializations = {
            entry.key for entry in powers[item.tag].specializations
            if entry.key != "state_birth_rate_mult"
        }
        if not expected_specializations <= set(assignment_keys):
            missing = sorted(expected_specializations - set(assignment_keys))
            raise ValidationError(
                f"{power_key} is missing merged specializations: {', '.join(missing)}"
            )
        decision_id = f"form_{item.tag.lower()}_decision"
        decision_match = re.search(rf"(?m)^{decision_id}\s*=\s*\{{", decision_text)
        decision_open = decision_text.find("{", decision_match.start(), decision_match.end())
        decision_body = extract_braced_block(decision_text, decision_open)
        for original in powers[item.tag].source_keys:
            if f"remove_modifier = {original}" not in decision_body:
                raise ValidationError(f"{decision_id} does not remove {original}")
        if f"name = {power_key}" not in decision_body:
            raise ValidationError(f"{decision_id} does not apply {power_key}")
        law_effect = superstate_law_effect_key(item)
        if f"{law_effect} = yes" not in decision_body:
            raise ValidationError(f"{decision_id} does not apply {law_effect}")
        expected_cultures = set(additional_primary_cultures(item, definitions, records))
        rendered_cultures = re.findall(
            r"(?m)^\s*add_primary_culture\s*=\s*cu:([a-z0-9_]+)\s*$",
            decision_body,
        )
        if len(rendered_cultures) != len(set(rendered_cultures)):
            raise ValidationError(f"{decision_id} adds a primary culture more than once")
        if set(rendered_cultures) != expected_cultures:
            missing = sorted(expected_cultures - set(rendered_cultures))
            extra = sorted(set(rendered_cultures) - expected_cultures)
            raise ValidationError(
                f"{decision_id} primary-culture mismatch; "
                f"missing={missing or 'none'}, extra={extra or 'none'}"
            )
        if f"exists = c:{item.tag}" not in effect_text or f"name = {power_key}" not in effect_text:
            raise ValidationError(f"Country-power effect does not maintain {power_key}")


def build_parser() -> argparse.ArgumentParser:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root, help="Mod repository root")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=default_root / "scripts" / "manifests" / "modern_superstates.toml",
        help="Superstate TOML manifest",
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=Path(r"D:\Steam\steamapps\common\Victoria 3\game"),
        help="Victoria 3 game directory used to validate COA textures",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write generated content")
    mode.add_argument("--check", action="store_true", help="Validate generated content is current")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve()
    game_root = args.game_root.resolve()
    try:
        definitions = parse_country_definitions(root / "common" / "country_definitions")
        records = parse_state_history(root / "common" / "history" / "states")
        superstates = load_manifest(manifest)
        power_effect_path = root / "common" / "scripted_effects" / "modern_country_power_effects.txt"
        power_modifier_path = root / "common" / "static_modifiers" / "modern_country_power_modifiers.txt"
        power_effect_source = power_effect_path.read_text(encoding="utf-8-sig")
        power_modifier_source = power_modifier_path.read_text(encoding="utf-8-sig")
        power_tag_map = parse_power_tag_map(power_effect_source)
        power_modifiers = parse_power_modifiers(power_modifier_source)
        law_effect_source = (
            root / "common" / "scripted_effects" / "modern_scripted_effects.txt"
        ).read_text(encoding="utf-8-sig")
        validate_law_effects(superstates, law_effect_source)
        validate_manifest(
            superstates,
            definitions,
            records,
            root / "common" / "history" / "states",
        )
        derive_states(superstates, records)
        validate_assets(superstates, game_root, root)
        powers = build_superstate_powers(superstates, power_tag_map, power_modifiers)
        outputs = expected_outputs(
            root,
            superstates,
            definitions,
            records,
            powers,
            power_effect_source,
            power_modifier_source,
        )
        validate_rendered_outputs(outputs, superstates, powers, definitions, records)
        if args.write:
            write_outputs(outputs)
        else:
            check_outputs(outputs)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
