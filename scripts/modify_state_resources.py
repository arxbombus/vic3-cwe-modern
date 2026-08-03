#!/usr/bin/env python3
"""
Multiply Victoria 3 state-region resource and arable-land amounts while preserving
all comments, commented-out content, whitespace, BOMs, line endings, and unrelated
text.

The script supports both capped resources and discovery resources:

    capped_resources = {
        building_iron_mine = 27
    }

    resource = {
        type = "building_gold_field"
        depleted_type = "building_gold_mine"
        discovered_amount = 4
        undiscovered_amount = 12
    }

Examples:

    uv run python scripts/modify_state_resources.py \
        scripts/base_state_regions \
        -o map_data/state_regions \
        --resource iron=2 \
        --resource gold=3

    uv run python scripts/modify_state_resources.py \
        scripts/base_state_regions \
        -o map_data/state_regions \
        --resource all=1.5 \
        --resource oil=3 \
        --arable-land 2

Specific resource rules override an ``all`` rule. ``--arable-land`` independently
multiplies every active ``arable_land = ...`` value and may be used by itself or
alongside resource rules. By default, directory mode:

1. Copies every input file to the output directory.
2. Modifies every ``*_replace.txt`` file.
3. Modifies standalone files that do not have a replacement counterpart.
4. Leaves superseded base files untouched in the output.

Use ``--file-mode all`` to modify every ``.txt`` file, including both original
and replacement definitions. This is usually not desirable for a mod that uses
replacement files.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path


NUMBER_PATTERN = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
CAPPED_ENTRY_RE = re.compile(
    rf"^(?P<indent>\s*)(?P<building>building_[A-Za-z0-9_]+)"
    rf"(?P<separator>\s*=\s*)(?P<value>{NUMBER_PATTERN})(?P<suffix>.*)$"
)
AMOUNT_ENTRY_RE = re.compile(
    rf"^(?P<indent>\s*)(?P<kind>discovered_amount|undiscovered_amount)"
    rf"(?P<separator>\s*=\s*)(?P<value>{NUMBER_PATTERN})(?P<suffix>.*)$"
)
ARABLE_LAND_RE = re.compile(
    rf"^(?P<indent>\s*)(?P<kind>arable_land)"
    rf"(?P<separator>\s*=\s*)(?P<value>{NUMBER_PATTERN})(?P<suffix>.*)$"
)
TYPE_RE = re.compile(
    r'\b(?P<kind>type|depleted_type)\s*=\s*"(?P<building>building_[A-Za-z0-9_]+)"'
)
BLOCK_START_RE = re.compile(
    r"^\s*(?P<name>capped_resources|resource)\s*=\s*\{"
)


RESOURCE_ALIASES: dict[str, frozenset[str]] = {
    "iron": frozenset({"building_iron_mine"}),
    "coal": frozenset({"building_coal_mine"}),
    "lead": frozenset({"building_lead_mine"}),
    "sulfur": frozenset({"building_sulfur_mine"}),
    "sulphur": frozenset({"building_sulfur_mine"}),
    "gold": frozenset({"building_gold_field", "building_gold_mine"}),
    "oil": frozenset({"building_oil_rig"}),
    "rubber": frozenset({"building_rubber_plantation"}),
    "logging": frozenset({"building_logging_camp"}),
    "wood": frozenset({"building_logging_camp"}),
    "fishing": frozenset({"building_fishing_wharf"}),
    "fish": frozenset({"building_fishing_wharf"}),
    "whaling": frozenset({"building_whaling_station"}),
    "whales": frozenset({"building_whaling_station"}),
    "copper": frozenset({"building_copper_mine"}),
    "bauxite": frozenset({"building_bauxite_mine"}),
    "silicon": frozenset({"building_silicon_mine"}),
    "rare_earth": frozenset({"building_rare_earth_elements_mine"}),
    "rare_earths": frozenset({"building_rare_earth_elements_mine"}),
    "uranium": frozenset({"building_uranium_mine"}),
    "phosphorus": frozenset({"building_phosphorus_mine"}),
    "phosphate": frozenset({"building_phosphorus_mine"}),
    "precious_minerals": frozenset({"building_precious_minerals_mine"}),
    "natural_gas": frozenset({"building_natural_gas_rig"}),
    "gas": frozenset({"building_natural_gas_rig"}),
}


@dataclass(frozen=True)
class ResourceRules:
    all_factor: Decimal | None
    building_factors: dict[str, Decimal]
    requested_names: tuple[str, ...]

    def factor_for(self, buildings: set[str]) -> tuple[Decimal | None, str | None]:
        """Return one factor for a capped entry or discovery-resource block."""
        matched = {
            self.building_factors[building]
            for building in buildings
            if building in self.building_factors
        }
        if len(matched) > 1:
            building_list = ", ".join(sorted(buildings))
            factor_list = ", ".join(str(value) for value in sorted(matched))
            raise ValueError(
                "Conflicting specific multipliers apply to one resource block "
                f"({building_list}): {factor_list}"
            )
        if matched:
            return next(iter(matched)), "specific"
        if self.all_factor is not None:
            return self.all_factor, "all"
        return None, None


@dataclass
class ChangeStats:
    entries: int = 0
    old_total: Decimal = Decimal(0)
    new_total: Decimal = Decimal(0)

    def record(self, old: Decimal, new: Decimal) -> None:
        self.entries += 1
        self.old_total += old
        self.new_total += new


@dataclass
class FileResult:
    path: Path
    changed: bool
    changes: int
    stats: dict[str, ChangeStats]


def parse_decimal(raw: str, *, label: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"Invalid {label}: {raw!r}") from exc
    if not value.is_finite():
        raise argparse.ArgumentTypeError(f"{label.capitalize()} must be finite")
    return value


def parse_resource_rule(raw: str) -> tuple[str, Decimal]:
    try:
        name, raw_factor = raw.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Expected RESOURCE=FACTOR, for example iron=2 or gold=3"
        ) from exc

    name = name.strip().lower().replace("-", "_")
    if not name:
        raise argparse.ArgumentTypeError("Resource name cannot be empty")

    factor = parse_decimal(raw_factor.strip(), label="resource multiplier")
    if factor < 0:
        raise argparse.ArgumentTypeError("Resource multiplier cannot be negative")

    if name != "all" and not name.startswith("building_") and name not in RESOURCE_ALIASES:
        known = ", ".join(sorted(RESOURCE_ALIASES))
        raise argparse.ArgumentTypeError(
            f"Unknown resource alias {name!r}. Use a building_* key or one of: {known}"
        )

    return name, factor


def build_rules(raw_rules: list[str]) -> ResourceRules:
    all_factor: Decimal | None = None
    building_factors: dict[str, Decimal] = {}
    building_sources: dict[str, str] = {}
    requested_names: list[str] = []

    for raw in raw_rules:
        name, factor = parse_resource_rule(raw)
        requested_names.append(name)

        if name == "all":
            if all_factor is not None:
                raise SystemExit("Duplicate --resource all=... rule")
            all_factor = factor
            continue

        buildings = (
            frozenset({name}) if name.startswith("building_") else RESOURCE_ALIASES[name]
        )
        for building in buildings:
            existing = building_factors.get(building)
            if existing is not None and existing != factor:
                source = building_sources[building]
                raise SystemExit(
                    f"Conflicting rules for {building}: {source}={existing} and {name}={factor}"
                )
            building_factors[building] = factor
            building_sources[building] = name

    return ResourceRules(
        all_factor=all_factor,
        building_factors=building_factors,
        requested_names=tuple(requested_names),
    )


def split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def split_code_comment(line_body: str) -> tuple[str, str]:
    """Split at the first # outside a quoted string."""
    in_string = False
    escaped = False
    for index, char in enumerate(line_body):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if char == "#" and not in_string:
            return line_body[:index], line_body[index:]
    return line_body, ""


def brace_delta(code: str) -> int:
    """Count braces outside quoted strings in uncommented code."""
    delta = 0
    in_string = False
    escaped = False
    for char in code:
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                delta += 1
            elif char == "}":
                delta -= 1
    return delta


def find_blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    blocks: list[tuple[str, int, int]] = []
    index = 0
    while index < len(lines):
        body, _ending = split_line_ending(lines[index])
        code, _comment = split_code_comment(body)
        match = BLOCK_START_RE.match(code)
        if match is None:
            index += 1
            continue

        depth = brace_delta(code)
        if depth <= 0:
            blocks.append((match.group("name"), index, index))
            index += 1
            continue

        end = index
        while depth > 0:
            end += 1
            if end >= len(lines):
                raise ValueError(
                    f"Unclosed {match.group('name')} block beginning on line {index + 1}"
                )
            end_body, _end_ending = split_line_ending(lines[end])
            end_code, _end_comment = split_code_comment(end_body)
            depth += brace_delta(end_code)
        blocks.append((match.group("name"), index, end))
        index = end + 1
    return blocks


def scaled_value(
    old: Decimal,
    factor: Decimal,
    *,
    rounding: str,
    minimum_positive: int,
) -> Decimal:
    raw = old * factor
    if rounding == "nearest":
        result = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    elif rounding == "floor":
        result = raw.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    elif rounding == "ceil":
        result = raw.quantize(Decimal("1"), rounding=ROUND_CEILING)
    else:
        raise ValueError(f"Unsupported rounding mode: {rounding}")

    if old > 0 and factor > 0 and result < minimum_positive:
        result = Decimal(minimum_positive)
    return result


def format_amount(value: Decimal) -> str:
    return str(int(value))


def replace_numeric_line(
    line: str,
    match: re.Match[str],
    new_value: Decimal,
) -> str:
    body, ending = split_line_ending(line)
    code, comment = split_code_comment(body)
    # The regex was matched against code, not the comment.
    new_code = (
        f"{match.group('indent')}"
        f"{match.groupdict().get('building') or match.groupdict().get('kind')}"
        f"{match.group('separator')}"
        f"{format_amount(new_value)}"
        f"{match.group('suffix')}"
    )
    return new_code + comment + ending


def process_text(
    text: str,
    *,
    rules: ResourceRules,
    arable_land_factor: Decimal | None,
    include_capped: bool,
    include_discovered: bool,
    include_undiscovered: bool,
    rounding: str,
    minimum_positive: int,
) -> tuple[str, int, dict[str, ChangeStats]]:
    lines = text.splitlines(keepends=True)
    blocks = find_blocks(lines)
    changes = 0
    stats: dict[str, ChangeStats] = defaultdict(ChangeStats)

    if arable_land_factor is not None:
        for index, line in enumerate(lines):
            body, _ending = split_line_ending(line)
            code, _comment = split_code_comment(body)
            match = ARABLE_LAND_RE.match(code)
            if match is None:
                continue
            old = Decimal(match.group("value"))
            new = scaled_value(
                old,
                arable_land_factor,
                rounding=rounding,
                minimum_positive=minimum_positive,
            )
            stats["arable_land"].record(old, new)
            if new != old:
                lines[index] = replace_numeric_line(lines[index], match, new)
                changes += 1

    for block_name, start, end in blocks:
        if block_name == "capped_resources":
            if not include_capped:
                continue
            for index in range(start + 1, end):
                body, _ending = split_line_ending(lines[index])
                code, _comment = split_code_comment(body)
                match = CAPPED_ENTRY_RE.match(code)
                if match is None:
                    continue
                building = match.group("building")
                factor, _source = rules.factor_for({building})
                if factor is None:
                    continue
                old = Decimal(match.group("value"))
                new = scaled_value(
                    old,
                    factor,
                    rounding=rounding,
                    minimum_positive=minimum_positive,
                )
                stats[f"capped:{building}"].record(old, new)
                if new != old:
                    lines[index] = replace_numeric_line(lines[index], match, new)
                    changes += 1
            continue

        # Discovery-resource block. Match against both type and depleted_type so
        # gold=... catches building_gold_field blocks and their gold-mine result.
        block_buildings: set[str] = set()
        for index in range(start, end + 1):
            body, _ending = split_line_ending(lines[index])
            code, _comment = split_code_comment(body)
            for match in TYPE_RE.finditer(code):
                block_buildings.add(match.group("building"))

        factor, _source = rules.factor_for(block_buildings)
        if factor is None:
            continue

        type_label = "+".join(sorted(block_buildings)) or "unknown"
        for index in range(start + 1, end):
            body, _ending = split_line_ending(lines[index])
            code, _comment = split_code_comment(body)
            match = AMOUNT_ENTRY_RE.match(code)
            if match is None:
                continue
            kind = match.group("kind")
            if kind == "discovered_amount" and not include_discovered:
                continue
            if kind == "undiscovered_amount" and not include_undiscovered:
                continue

            old = Decimal(match.group("value"))
            new = scaled_value(
                old,
                factor,
                rounding=rounding,
                minimum_positive=minimum_positive,
            )
            stats[f"{kind}:{type_label}"].record(old, new)
            if new != old:
                lines[index] = replace_numeric_line(lines[index], match, new)
                changes += 1

    return "".join(lines), changes, dict(stats)


def normalized_region_stem(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_replace"):
        stem = stem[: -len("_replace")]
    return stem.rstrip("_").lower()


def effective_files(root: Path, *, file_mode: str) -> set[Path]:
    files = {path for path in root.rglob("*.txt") if path.is_file()}
    if file_mode == "all":
        return files
    if file_mode == "replace-only":
        return {path for path in files if path.stem.endswith("_replace")}

    replacement_stems = {
        normalized_region_stem(path)
        for path in files
        if path.stem.endswith("_replace")
    }
    selected: set[Path] = set()
    for path in files:
        if path.stem.endswith("_replace"):
            selected.add(path)
        elif normalized_region_stem(path) not in replacement_stems:
            selected.add(path)
    return selected


def read_preserving_encoding(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom


def write_preserving_encoding(path: Path, text: str, *, has_bom: bool) -> None:
    encoded = text.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def process_file(
    source: Path,
    destination: Path,
    *,
    rules: ResourceRules,
    arable_land_factor: Decimal | None,
    include_capped: bool,
    include_discovered: bool,
    include_undiscovered: bool,
    rounding: str,
    minimum_positive: int,
) -> FileResult:
    text, has_bom = read_preserving_encoding(source)
    output, changes, stats = process_text(
        text,
        rules=rules,
        arable_land_factor=arable_land_factor,
        include_capped=include_capped,
        include_discovered=include_discovered,
        include_undiscovered=include_undiscovered,
        rounding=rounding,
        minimum_positive=minimum_positive,
    )
    write_preserving_encoding(destination, output, has_bom=has_bom)
    return FileResult(destination, output != text, changes, stats)


def merge_stats(
    target: dict[str, ChangeStats],
    incoming: dict[str, ChangeStats],
) -> None:
    for key, value in incoming.items():
        current = target.setdefault(key, ChangeStats())
        current.entries += value.entries
        current.old_total += value.old_total
        current.new_total += value.new_total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Multiply capped, discovered, and undiscovered state-region resource "
            "amounts and/or arable_land."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input state-region file or directory.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Output file or directory. Directory input defaults to "
            "<input_name>_modified; file input defaults to <stem>_modified<suffix>."
        ),
    )
    parser.add_argument(
        "--resource",
        action="append",
        default=[],
        metavar="RESOURCE=FACTOR",
        help=(
            "Resource multiplier. Repeatable. Examples: iron=2, gold=3, "
            "building_oil_rig=4, all=1.5. Specific rules override all=..."
        ),
    )
    parser.add_argument(
        "--arable-land",
        type=lambda raw: parse_decimal(raw, label="arable-land multiplier"),
        metavar="FACTOR",
        help=(
            "Multiply every active arable_land value by FACTOR. May be used without "
            "--resource. Example: --arable-land 2"
        ),
    )
    parser.add_argument(
        "--file-mode",
        choices=("effective", "replace-only", "all"),
        default="effective",
        help=(
            "Directory files to modify: effective (replacement files plus standalone files), "
            "replace-only, or all. Every file is still copied. Default: effective."
        ),
    )
    parser.add_argument(
        "--exclude-capped",
        action="store_true",
        help="Do not modify capped_resources entries.",
    )
    parser.add_argument(
        "--exclude-discovered",
        action="store_true",
        help="Do not modify discovered_amount entries.",
    )
    parser.add_argument(
        "--exclude-undiscovered",
        action="store_true",
        help="Do not modify undiscovered_amount entries.",
    )
    parser.add_argument(
        "--round",
        choices=("nearest", "floor", "ceil"),
        default="nearest",
        help="Rounding for non-integer results. Default: nearest, half up.",
    )
    parser.add_argument(
        "--minimum-positive",
        type=int,
        default=1,
        help=(
            "Minimum result when the original amount and factor are positive. "
            "Use 0 to allow small scaled values to round to zero. Default: 1."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report intended changes without creating output files.",
    )
    return parser.parse_args()


def default_output(source: Path) -> Path:
    if source.is_dir():
        return source.with_name(f"{source.name}_modified")
    return source.with_name(f"{source.stem}_modified{source.suffix}")


def main() -> None:
    args = parse_args()
    source = args.input.resolve()
    if not source.exists():
        raise SystemExit(f"Input does not exist: {source}")
    if args.minimum_positive < 0:
        raise SystemExit("--minimum-positive cannot be negative")

    if (
        args.exclude_capped
        and args.exclude_discovered
        and args.exclude_undiscovered
        and args.arable_land is None
    ):
        raise SystemExit("All resource amount categories are excluded; nothing can be changed")

    if args.arable_land is not None and args.arable_land < 0:
        raise SystemExit("--arable-land multiplier cannot be negative")
    if not args.resource and args.arable_land is None:
        raise SystemExit(
            "Provide at least one --resource RESOURCE=FACTOR rule or --arable-land FACTOR"
        )

    rules = build_rules(args.resource)
    destination = (args.output or default_output(source)).resolve()

    if source == destination:
        raise SystemExit("Input and output must be different paths")

    aggregate: dict[str, ChangeStats] = {}
    processed = 0
    changed_files = 0
    total_changes = 0

    if source.is_file():
        if args.dry_run:
            text, _has_bom = read_preserving_encoding(source)
            _output, changes, stats = process_text(
                text,
                rules=rules,
                arable_land_factor=args.arable_land,
                include_capped=not args.exclude_capped,
                include_discovered=not args.exclude_discovered,
                include_undiscovered=not args.exclude_undiscovered,
                rounding=args.round,
                minimum_positive=args.minimum_positive,
            )
            processed = 1
            changed_files = int(changes > 0)
            total_changes = changes
            merge_stats(aggregate, stats)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = process_file(
                source,
                destination,
                rules=rules,
                arable_land_factor=args.arable_land,
                include_capped=not args.exclude_capped,
                include_discovered=not args.exclude_discovered,
                include_undiscovered=not args.exclude_undiscovered,
                rounding=args.round,
                minimum_positive=args.minimum_positive,
            )
            processed = 1
            changed_files = int(result.changed)
            total_changes = result.changes
            merge_stats(aggregate, result.stats)
    else:
        selected = effective_files(source, file_mode=args.file_mode)
        all_files = [path for path in source.rglob("*") if path.is_file()]

        if not args.dry_run:
            if destination.exists():
                shutil.rmtree(destination)
            destination.mkdir(parents=True, exist_ok=True)

        for path in all_files:
            relative = path.relative_to(source)
            out_path = destination / relative
            if path not in selected:
                if not args.dry_run:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, out_path)
                continue

            processed += 1
            if args.dry_run:
                text, _has_bom = read_preserving_encoding(path)
                _output, changes, stats = process_text(
                    text,
                    rules=rules,
                    arable_land_factor=args.arable_land,
                    include_capped=not args.exclude_capped,
                    include_discovered=not args.exclude_discovered,
                    include_undiscovered=not args.exclude_undiscovered,
                    rounding=args.round,
                    minimum_positive=args.minimum_positive,
                )
                changed = changes > 0
            else:
                result = process_file(
                    path,
                    out_path,
                    rules=rules,
                    arable_land_factor=args.arable_land,
                    include_capped=not args.exclude_capped,
                    include_discovered=not args.exclude_discovered,
                    include_undiscovered=not args.exclude_undiscovered,
                    rounding=args.round,
                    minimum_positive=args.minimum_positive,
                )
                changes = result.changes
                stats = result.stats
                changed = result.changed

            changed_files += int(changed)
            total_changes += changes
            merge_stats(aggregate, stats)

    action = "Would create" if args.dry_run else "Created"
    if not args.dry_run:
        print(f"{action}: {destination}")
    else:
        print("Dry run: no files written")
    print(f"File mode: {args.file_mode}")
    print(f"Files scanned for modification: {processed}")
    print(f"Files with changes: {changed_files}")
    print(f"Numeric entries changed: {total_changes}")
    print("Resource rules:")
    if args.arable_land is not None:
        print(f"  arable_land: {args.arable_land}x")
    if rules.all_factor is not None:
        print(f"  all: {rules.all_factor}x")
    for building, factor in sorted(rules.building_factors.items()):
        print(f"  {building}: {factor}x")

    if aggregate:
        print("Changed totals:")
        for key, stat in sorted(aggregate.items()):
            print(
                f"  {key}: {format_amount(stat.old_total)} -> "
                f"{format_amount(stat.new_total)} across {stat.entries} entries"
            )
    else:
        print("No matching resource entries were found.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Error: {exc}") from exc