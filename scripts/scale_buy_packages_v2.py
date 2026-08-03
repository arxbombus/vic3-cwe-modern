#!/usr/bin/env python3
"""
Scale Victoria 3 buy packages by wealth level and optionally boost individual
popneed categories.

Global default curve:

    global_multiplier = 1.5 ** (max(0, wealth - 30) / 20)

Per-popneed constant multiplier:

    --need-multiplier popneed_luxury_items=1.50
    --need-multiplier popneed_leisure=2.00@30

The optional "@30" means the extra multiplier begins at wealth_30. Without an
explicit start wealth, the multiplier applies at every wealth level where that
popneed already exists.

Per-popneed exponential curve:

    --need-curve popneed_luxury_items=1.40,30,20

This means an additional multiplier of:

    1.40 ** (max(0, wealth - 30) / 20)

All multipliers stack multiplicatively:

    new_value = old_value
                * global_wealth_multiplier
                * per_need_constant_multiplier
                * per_need_curve_multiplier

The script never inserts a missing popneed into a package. It only scales
popneed_* entries already present and recalculates each "# Sum =" comment.

Examples:

    python scale_buy_packages_v2.py 00_buy_packages.txt

    python scale_buy_packages_v2.py 00_buy_packages.txt \
        -o 00_buy_packages_scaled.txt \
        --start-wealth 20 \
        --interval 20 \
        --multiplier 1.85 \
        --need-multiplier popneed_luxury_items=1.50@20 \
        --need-multiplier popneed_leisure=1.75@20

    python scale_buy_packages_v2.py 00_buy_packages.txt \
        --no-global-scale \
        --need-multiplier popneed_luxury_items=1.50@20 \
        --need-curve popneed_leisure=1.30,30,20

    uv run python scripts/scale_buy_packages_v2.py scripts/base_buy_packages.txt -o ../common/buy_packages/00_buy_packages.txt --start-wealth 15 --interval 20 --multiplier 1.5 --need-multiplier popneed_luxury_items=1.85@15

    WINDOWS
    uv run python 'scripts\scale_buy_packages_v2.py' 'scripts\base_buy_packages.txt' -o 'common\buy_packages\00_buy_packages.txt' --start-wealth 15 --interval 20 --multiplier 1.6 --need-multiplier popneed_luxury_items=2@15 --need-multiplier popneed_services=2@15
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path


WEALTH_RE = re.compile(r"^\s*wealth_(\d+)\s*=\s*\{")
GOODS_RE = re.compile(r"^\s*goods\s*=\s*\{")
VALUE_RE = re.compile(
    r"^(\s*)(popneed_[A-Za-z0-9_]+)(\s*=\s*)(-?\d+)(.*)$"
)
SUM_RE = re.compile(r"#\s*Sum\s*=\s*\d+")


@dataclass(frozen=True)
class ConstantNeedRule:
    factor: float
    start_wealth: int


@dataclass(frozen=True)
class CurveNeedRule:
    interval_multiplier: float
    start_wealth: int
    interval: float


def parse_constant_need_rule(value: str) -> tuple[str, ConstantNeedRule]:
    """
    Parse:
        popneed_luxury_items=1.5
        popneed_luxury_items=1.5@20
    """
    try:
        name, raw_rule = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Expected NEED=FACTOR or NEED=FACTOR@START_WEALTH"
        ) from exc

    name = name.strip()
    if not name.startswith("popneed_"):
        raise argparse.ArgumentTypeError(
            f"Need name must start with 'popneed_': {name!r}"
        )

    if "@" in raw_rule:
        raw_factor, raw_start = raw_rule.split("@", 1)
        try:
            start_wealth = int(raw_start)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid start wealth in {value!r}"
            ) from exc
    else:
        raw_factor = raw_rule
        start_wealth = 1

    try:
        factor = float(raw_factor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid multiplier in {value!r}"
        ) from exc

    if factor <= 0:
        raise argparse.ArgumentTypeError("Need multiplier must be greater than zero")

    if start_wealth < 1:
        raise argparse.ArgumentTypeError("Start wealth must be at least 1")

    return name, ConstantNeedRule(
        factor=factor,
        start_wealth=start_wealth,
    )


def parse_curve_need_rule(value: str) -> tuple[str, CurveNeedRule]:
    """
    Parse:
        popneed_luxury_items=1.4,30,20

    Meaning:
        1.4 ** (max(0, wealth - 30) / 20)
    """
    try:
        name, raw_rule = value.split("=", 1)
        raw_multiplier, raw_start, raw_interval = raw_rule.split(",", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Expected NEED=MULTIPLIER,START_WEALTH,INTERVAL"
        ) from exc

    name = name.strip()
    if not name.startswith("popneed_"):
        raise argparse.ArgumentTypeError(
            f"Need name must start with 'popneed_': {name!r}"
        )

    try:
        interval_multiplier = float(raw_multiplier)
        start_wealth = int(raw_start)
        interval = float(raw_interval)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid need curve in {value!r}"
        ) from exc

    if interval_multiplier <= 0:
        raise argparse.ArgumentTypeError(
            "Need curve multiplier must be greater than zero"
        )

    if start_wealth < 1:
        raise argparse.ArgumentTypeError("Start wealth must be at least 1")

    if interval <= 0:
        raise argparse.ArgumentTypeError("Need curve interval must be greater than zero")

    return name, CurveNeedRule(
        interval_multiplier=interval_multiplier,
        start_wealth=start_wealth,
        interval=interval,
    )


def exponential_multiplier(
    wealth: int,
    *,
    start_wealth: int,
    interval: float,
    interval_multiplier: float,
) -> float:
    effective_levels = max(0, wealth - start_wealth)
    return interval_multiplier ** (effective_levels / interval)


def per_need_multiplier(
    need: str,
    wealth: int,
    *,
    constant_rules: dict[str, ConstantNeedRule],
    curve_rules: dict[str, CurveNeedRule],
) -> float:
    result = 1.0

    constant_rule = constant_rules.get(need)
    if constant_rule is not None and wealth >= constant_rule.start_wealth:
        result *= constant_rule.factor

    curve_rule = curve_rules.get(need)
    if curve_rule is not None:
        result *= exponential_multiplier(
            wealth,
            start_wealth=curve_rule.start_wealth,
            interval=curve_rule.interval,
            interval_multiplier=curve_rule.interval_multiplier,
        )

    return result


def scale_buy_packages(
    source: Path,
    destination: Path,
    *,
    start_wealth: int,
    interval: float,
    interval_multiplier: float,
    global_scale_enabled: bool,
    constant_rules: dict[str, ConstantNeedRule],
    curve_rules: dict[str, CurveNeedRule],
) -> tuple[
    dict[int, dict[str, float | int]],
    dict[str, dict[str, int]],
]:
    if interval <= 0:
        raise ValueError("interval must be greater than zero")

    if interval_multiplier <= 0:
        raise ValueError("interval_multiplier must be greater than zero")

    text = source.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    current_wealth: int | None = None
    in_goods = False
    goods_start: int | None = None
    goods_sum = 0

    package_results: dict[int, dict[str, float | int]] = {}
    need_results: dict[str, dict[str, int]] = {}

    for index, line in enumerate(lines):
        wealth_match = WEALTH_RE.match(line)
        if wealth_match:
            current_wealth = int(wealth_match.group(1))

            global_multiplier = (
                exponential_multiplier(
                    current_wealth,
                    start_wealth=start_wealth,
                    interval=interval,
                    interval_multiplier=interval_multiplier,
                )
                if global_scale_enabled
                else 1.0
            )

            package_results[current_wealth] = {
                "global_multiplier": global_multiplier,
                "old_sum": 0,
                "new_sum": 0,
                "changed": 0,
            }
            continue

        if current_wealth is not None and GOODS_RE.match(line):
            in_goods = True
            goods_start = index
            goods_sum = 0
            continue

        if not in_goods:
            continue

        if line.strip() == "}":
            if goods_start is None:
                raise RuntimeError("Reached end of goods block without its header")

            header = lines[goods_start]
            if SUM_RE.search(header):
                lines[goods_start] = SUM_RE.sub(f"# Sum = {goods_sum}", header)
            else:
                lines[goods_start] = header.rstrip() + f" # Sum = {goods_sum}"

            in_goods = False
            goods_start = None
            continue

        value_match = VALUE_RE.match(line)
        if value_match is None or current_wealth is None:
            continue

        need = value_match.group(2)
        old_value = int(value_match.group(4))

        global_multiplier = float(
            package_results[current_wealth]["global_multiplier"]
        )
        need_multiplier = per_need_multiplier(
            need,
            current_wealth,
            constant_rules=constant_rules,
            curve_rules=curve_rules,
        )
        combined_multiplier = global_multiplier * need_multiplier

        if old_value <= 0:
            new_value = old_value
        else:
            new_value = max(1, round(old_value * combined_multiplier))

        package_results[current_wealth]["old_sum"] = (
            int(package_results[current_wealth]["old_sum"]) + old_value
        )
        package_results[current_wealth]["new_sum"] = (
            int(package_results[current_wealth]["new_sum"]) + new_value
        )
        goods_sum += new_value

        need_stats = need_results.setdefault(
            need,
            {
                "entries": 0,
                "changed_entries": 0,
                "old_total": 0,
                "new_total": 0,
            },
        )
        need_stats["entries"] += 1
        need_stats["old_total"] += old_value
        need_stats["new_total"] += new_value

        if new_value != old_value:
            package_results[current_wealth]["changed"] = (
                int(package_results[current_wealth]["changed"]) + 1
            )
            need_stats["changed_entries"] += 1
            lines[index] = (
                f"{value_match.group(1)}"
                f"{need}"
                f"{value_match.group(3)}"
                f"{new_value}"
                f"{value_match.group(5)}"
            )

    if in_goods:
        raise RuntimeError("Input ended inside a goods block")

    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return package_results, need_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scale Victoria 3 buy packages globally and by individual popneed."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the original buy-package file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path. Defaults to <input_stem>_scaled<input_suffix>.",
    )

    global_group = parser.add_argument_group("global wealth scaling")
    global_group.add_argument(
        "--start-wealth",
        type=int,
        default=30,
        help="Global curve anchor wealth. Default: 30.",
    )
    global_group.add_argument(
        "--interval",
        type=float,
        default=20,
        help="Global wealth levels per multiplier interval. Default: 20.",
    )
    global_group.add_argument(
        "--multiplier",
        type=float,
        default=1.5,
        help="Global multiplier reached per interval. Default: 1.5.",
    )
    global_group.add_argument(
        "--no-global-scale",
        action="store_true",
        help="Disable the global wealth curve and apply only per-popneed rules.",
    )

    need_group = parser.add_argument_group("per-popneed scaling")
    need_group.add_argument(
        "--need-multiplier",
        action="append",
        default=[],
        metavar="NEED=FACTOR[@START]",
        help=(
            "Apply an extra constant multiplier to one need. Repeatable. "
            "Example: popneed_luxury_items=1.5@20"
        ),
    )
    need_group.add_argument(
        "--need-curve",
        action="append",
        default=[],
        metavar="NEED=MULTIPLIER,START,INTERVAL",
        help=(
            "Apply an extra exponential curve to one need. Repeatable. "
            "Example: popneed_leisure=1.3,30,20"
        ),
    )

    return parser.parse_args()


def build_rule_maps(
    constant_values: list[str],
    curve_values: list[str],
) -> tuple[
    dict[str, ConstantNeedRule],
    dict[str, CurveNeedRule],
]:
    constant_rules: dict[str, ConstantNeedRule] = {}
    curve_rules: dict[str, CurveNeedRule] = {}

    for value in constant_values:
        name, rule = parse_constant_need_rule(value)
        if name in constant_rules:
            raise SystemExit(
                f"Duplicate --need-multiplier rule for {name}"
            )
        constant_rules[name] = rule

    for value in curve_values:
        name, rule = parse_curve_need_rule(value)
        if name in curve_rules:
            raise SystemExit(
                f"Duplicate --need-curve rule for {name}"
            )
        curve_rules[name] = rule

    return constant_rules, curve_rules


def main() -> None:
    args = parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Input file does not exist: {args.input}")

    if args.start_wealth < 1:
        raise SystemExit("--start-wealth must be at least 1")

    output = args.output or args.input.with_name(
        f"{args.input.stem}_scaled{args.input.suffix}"
    )

    constant_rules, curve_rules = build_rule_maps(
        args.need_multiplier,
        args.need_curve,
    )

    package_results, need_results = scale_buy_packages(
        args.input,
        output,
        start_wealth=args.start_wealth,
        interval=args.interval,
        interval_multiplier=args.multiplier,
        global_scale_enabled=not args.no_global_scale,
        constant_rules=constant_rules,
        curve_rules=curve_rules,
    )

    print(f"Created: {output}")
    print(f"Packages processed: {len(package_results)}")

    if args.no_global_scale:
        print("Global wealth scaling: disabled")
    else:
        print(
            "Global formula: "
            f"{args.multiplier} ** "
            f"(max(0, wealth - {args.start_wealth}) / {args.interval})"
        )

    if constant_rules:
        print("Constant per-popneed rules:")
        for need, rule in sorted(constant_rules.items()):
            print(
                f"  {need}: {rule.factor:g}x "
                f"from wealth_{rule.start_wealth}"
            )

    if curve_rules:
        print("Exponential per-popneed rules:")
        for need, rule in sorted(curve_rules.items()):
            print(
                f"  {need}: {rule.interval_multiplier:g} ** "
                f"(max(0, wealth - {rule.start_wealth}) / "
                f"{rule.interval:g})"
            )

    print("Package checkpoints:")
    for wealth in (20, 30, 40, 50, 70, 90, 99):
        if wealth not in package_results:
            continue

        result = package_results[wealth]
        print(
            f"  wealth_{wealth}: "
            f"global {float(result['global_multiplier']):.4f}x | "
            f"{int(result['old_sum']):,} -> "
            f"{int(result['new_sum']):,}"
        )

    requested_needs = set(constant_rules) | set(curve_rules)
    if requested_needs:
        print("Requested popneed totals:")
        for need in sorted(requested_needs):
            stats = need_results.get(need)
            if stats is None:
                print(f"  {need}: not found in the input file")
                continue

            print(
                f"  {need}: "
                f"{stats['old_total']:,} -> {stats['new_total']:,} "
                f"across {stats['changed_entries']}/{stats['entries']} "
                "changed entries"
            )


if __name__ == "__main__":
    main()
