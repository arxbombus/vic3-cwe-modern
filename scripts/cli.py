from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Callable, Iterable, cast
import math
import re

import questionary
from questionary import Style
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


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

app = typer.Typer(no_args_is_help=True, pretty_exceptions_short=True)
_console = Console(stderr=True)
_err_console = Console(stderr=True)

QUESTIONARY_STYLE = Style(
    [
        ("qmark", "fg:#00afff bold"),
        ("question", "bold"),
        ("answer", "fg:#00ff87 bold"),
        ("pointer", "fg:#00afff bold"),
        ("highlighted", "fg:#00afff bold"),
        ("selected", "fg:#00ff87"),
        ("separator", "fg:#888888"),
        ("instruction", "fg:#888888"),
        ("text", ""),
        ("disabled", "fg:#666666 italic"),
    ]
)


def _find_mod_root(start: Path) -> Path:
    start = start.resolve()
    for p in [start] + list(start.parents):
        if (p / "common").exists() and (p / "scripts" / "pyproject.toml").exists():
            return p
    return start.parent.parent


MOD_ROOT = _find_mod_root(Path(__file__))
SCRIPTS_ROOT = MOD_ROOT / "scripts"
BACKUP_BASE_DIR = SCRIPTS_ROOT / ".backups"
BASELINE_DATA_BASE_DIR = SCRIPTS_ROOT / ".baseline_data"


def _resolve_user_path(p: Path) -> Path:
    return p.resolve() if p.is_absolute() else (MOD_ROOT / p).resolve()


def _q_select(message: str, *, choices: list[str], default: str | None = None) -> str:
    ans = questionary.select(
        message,
        choices=choices,
        default=default,
        show_selected=True,
        use_indicator=True,
        pointer="▶",
        use_arrow_keys=True,
    ).ask()

    if ans is None:
        raise typer.Abort()
    return ans


def _q_confirm(message: str, *, default: bool = True) -> bool:
    ans = questionary.confirm(
        message,
        default=default,
    ).ask()

    if ans is None:
        raise typer.Abort()
    return bool(ans)


def _q_checkbox(message: str, *, choices: list[str]) -> list[str]:
    ans = questionary.checkbox(
        message,
        choices=choices,
    ).ask()

    if not ans:
        raise typer.Abort()
    return list(ans)


def generic_schema() -> DocumentSchema:
    root = KeyRule(name="root", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=True))
    return DocumentSchema(name="generic", root_key="root", root_rule=root)


@dataclass(frozen=True)
class EditRule:
    name: str
    description: str
    predicate: Callable[[tuple[str, ...], ClausewitzEntry], bool]
    apply: Callable[[tuple[str, ...], ClausewitzEntry, "EditContext"], None]


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


@dataclass(frozen=True)
class PlanConfig:
    plan: EditPlan
    default_dir: Path
    default_factor: float
    title: str
    uses_factor: bool = True
    context_builder: Callable[[ClausewitzDocument, float], EditContext] | None = None
    text_plan: TextEditPlan | None = None


def _iter_entries(
    block: ClausewitzBlock, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], ClausewitzEntry]]:
    for entry in block.entries:
        key = str(entry.key)
        current_path = path + (key,)
        yield current_path, entry
        if isinstance(entry.value, ClausewitzBlock):
            yield from _iter_entries(entry.value, current_path)
        elif isinstance(entry.value, ClausewitzList):
            for item in entry.value.values:
                if isinstance(item, ClausewitzBlock):
                    yield from _iter_entries(item, current_path)


def _in_building_level_scaled(path: tuple[str, ...]) -> bool:
    return (
        len(path) >= 3
        and path[-3] == "building_modifiers"
        and path[-2] == "level_scaled"
    )


def _apply_edits(
    document: ClausewitzDocument, plan: EditPlan, context: EditContext, dry_run: bool
) -> dict[str, int]:
    counts = {edit.name: 0 for edit in plan.edits}
    for path, entry in _iter_entries(document.root):
        for edit in plan.edits:
            if edit.predicate(path, entry):
                counts[edit.name] += 1
                if not dry_run:
                    edit.apply(path, entry, context)
    return counts


def _apply_text_edits(text: str, plan: TextEditPlan) -> tuple[str, dict[str, int]]:
    counts = {edit.name: 0 for edit in plan.edits}
    updated = text
    for edit in plan.edits:
        updated, count = edit.apply(updated)
        counts[edit.name] += count
    return updated, counts


def _format_factor(config: PlanConfig, factor: float) -> str:
    return str(factor) if config.uses_factor else "n/a"


def _context_for_document(
    config: PlanConfig, document: ClausewitzDocument, factor: float
) -> EditContext:
    if config.context_builder is None:
        return EditContext(factor=factor)
    return config.context_builder(document, factor)


def _format_document(document: ClausewitzDocument, *, preserve: bool = True) -> str:
    formatter = ClausewitzFormatter(mode="preserve" if preserve else "format")
    return formatter.format_document(document)


def _build_production_method_plan() -> EditPlan:
    def is_building_employment(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        if not _in_building_level_scaled(path):
            return False
        key = str(entry.key)
        return (
            key.startswith("building_employment_")
            and key.endswith("_add")
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_entry(
        path: tuple[str, ...], entry: ClausewitzEntry, context: EditContext
    ) -> None:
        _ = path
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for scaling")
        if context.factor == 0:
            raise ValueError("Scaling factor cannot be 0")
        scaled = entry.value.value * context.factor
        entry.value.value = (
            int(scaled) if isinstance(entry.value.value, int) else scaled
        )
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_building_employment_add",
            description="Scale building_employment_*_add under building_modifiers/level_scaled by factor",
            predicate=is_building_employment,
            apply=scale_entry,
        )
    ]
    return EditPlan(name="production_methods", edits=edits)


def _build_goods_plan() -> EditPlan:
    def is_goods_cost(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        _ = path
        return (
            entry.key == "cost"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_cost(
        path: tuple[str, ...], entry: ClausewitzEntry, context: EditContext
    ) -> None:
        _ = path
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for scaling")
        if context.factor == 0:
            raise ValueError("Scaling factor cannot be 0")
        scaled = entry.value.value * context.factor
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_goods_cost",
            description="Scale goods cost by factor",
            predicate=is_goods_cost,
            apply=scale_cost,
        )
    ]
    return EditPlan(name="goods", edits=edits)


def _build_pop_types_plan() -> EditPlan:
    def is_wage_weight(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        _ = path
        return (
            entry.key == "wage_weight"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def is_dependent_wage(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        _ = path
        return (
            entry.key == "dependent_wage"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_wage_weight(
        path: tuple[str, ...], entry: ClausewitzEntry, context: EditContext
    ) -> None:
        _ = path
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for wage_weight")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for wage_weight")
        scaled = entry.value.value * 1.5
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    def scale_dependent_wage(
        path: tuple[str, ...], entry: ClausewitzEntry, context: EditContext
    ) -> None:
        _ = path
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for dependent_wage")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for dependent_wage")
        scaled = entry.value.value * 0.25
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_wage_weight",
            description="Multiply wage_weight by 1.5",
            predicate=is_wage_weight,
            apply=scale_wage_weight,
        ),
        EditRule(
            name="scale_dependent_wage",
            description="Multiply dependent_wage by 0.25",
            predicate=is_dependent_wage,
            apply=scale_dependent_wage,
        ),
    ]
    return EditPlan(name="pop_types", edits=edits)


def _format_scaled_value(original: str, scaled: float) -> str:
    if "." not in original and "e" not in original and "E" not in original:
        if scaled.is_integer():
            return str(int(scaled))
    return str(scaled)


def _scale_key_value_text(
    text: str, key: str, factor: float
) -> tuple[str, int]:
    pattern = re.compile(rf"(\b{re.escape(key)}\s*=\s*)(-?\d+(?:\.\d+)?)")

    def repl(match: re.Match[str]) -> str:
        raw_value = match.group(2)
        scaled = float(raw_value) * factor
        return match.group(1) + _format_scaled_value(raw_value, scaled)

    return pattern.subn(repl, text)


def _build_pop_types_text_plan_with_factors(
    wage_weight_factor: float, dependent_wage_factor: float
) -> TextEditPlan:
    def apply_wage_weight(text: str) -> tuple[str, int]:
        return _scale_key_value_text(text, "wage_weight", wage_weight_factor)

    def apply_dependent_wage(text: str) -> tuple[str, int]:
        return _scale_key_value_text(text, "dependent_wage", dependent_wage_factor)

    edits = [
        TextEditRule(
            name="scale_wage_weight",
            description="Multiply wage_weight by factor",
            apply=apply_wage_weight,
        ),
        TextEditRule(
            name="scale_dependent_wage",
            description="Multiply dependent_wage by factor",
            apply=apply_dependent_wage,
        ),
    ]
    return TextEditPlan(name="pop_types", edits=edits)


def _build_pop_types_text_plan() -> TextEditPlan:
    return _build_pop_types_text_plan_with_factors(
        POP_TYPES_WAGE_WEIGHT_FACTOR, POP_TYPES_DEPENDENT_WAGE_FACTOR
    )


def _parse_wealth_level(key: str) -> int | None:
    match = re.fullmatch(r"wealth_(\d+)", key)
    if match is None:
        return None
    return int(match.group(1))


def _build_buy_packages_plan() -> EditPlan:
    def is_popneed_goods(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        if len(path) < 3 or path[-2] != "goods":
            return False
        if _parse_wealth_level(path[-3]) is None:
            return False
        key = str(entry.key)
        return (
            key.startswith("popneed_")
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_popneed(
        path: tuple[str, ...], entry: ClausewitzEntry, context: EditContext
    ) -> None:
        wealth_level = _parse_wealth_level(path[-3])
        if wealth_level is None:
            return
        if context.wealth_min is None or context.wealth_max is None:
            multiplier = 1.0
        elif context.wealth_max <= context.wealth_min:
            multiplier = 1.0
        else:
            t = (wealth_level - context.wealth_min) / (
                context.wealth_max - context.wealth_min
            )
            curve_max = context.curve_max if context.curve_max is not None else 2.0
            curve_power = (
                context.curve_power if context.curve_power is not None else 1.0
            )
            multiplier = math.pow(curve_max, t**curve_power)
            if multiplier > curve_max:
                multiplier = curve_max

        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for popneed scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for popneed scaling")
        scaled = int(entry.value.value * multiplier)
        entry.value.value = scaled
        entry.value.raw = str(entry.value.value)

    edits = [
        EditRule(
            name="scale_popneed_goods",
            description="Scale popneed_* by exponential wealth curve (max 2x)",
            predicate=is_popneed_goods,
            apply=scale_popneed,
        )
    ]
    return EditPlan(name="buy_packages", edits=edits)


PRODUCTION_METHODS_EMPLOYMENT_FACTOR = 2.0
GOODS_COST_FACTOR = 1.5
POP_TYPES_WAGE_WEIGHT_FACTOR = 1.5
POP_TYPES_DEPENDENT_WAGE_FACTOR = 0.25
BUY_PACKAGES_CURVE_MAX = 2.0
BUY_PACKAGES_CURVE_POWER = 1.0

PRODUCTION_METHODS_PLAN = _build_production_method_plan()
GOODS_PLAN = _build_goods_plan()
POP_TYPES_PLAN = _build_pop_types_plan()
POP_TYPES_TEXT_PLAN = _build_pop_types_text_plan()
BUY_PACKAGES_PLAN = _build_buy_packages_plan()


def _find_wealth_range(document: ClausewitzDocument) -> tuple[int | None, int | None]:
    wealth_values: list[int] = []
    for entry in document.root.entries:
        key = str(entry.key)
        wealth_level = _parse_wealth_level(key)
        if wealth_level is not None:
            wealth_values.append(wealth_level)
    if not wealth_values:
        return None, None
    return min(wealth_values), max(wealth_values)


def _buy_packages_context_builder(
    document: ClausewitzDocument, factor: float
) -> EditContext:
    wealth_min, wealth_max = _find_wealth_range(document)
    return EditContext(
        factor=factor,
        wealth_min=wealth_min,
        wealth_max=wealth_max,
        curve_max=BUY_PACKAGES_CURVE_MAX,
        curve_power=BUY_PACKAGES_CURVE_POWER,
    )


def _build_buy_packages_context_builder(
    curve_max: float, curve_power: float
) -> Callable[[ClausewitzDocument, float], EditContext]:
    def builder(document: ClausewitzDocument, factor: float) -> EditContext:
        wealth_min, wealth_max = _find_wealth_range(document)
        return EditContext(
            factor=factor,
            wealth_min=wealth_min,
            wealth_max=wealth_max,
            curve_max=curve_max,
            curve_power=curve_power,
        )

    return builder


def _prompt_scale(message: str, default: float) -> float:
    value = cast(float, typer.prompt(message, default=default))
    if value == 0:
        raise typer.BadParameter("factor cannot be 0")
    return value


def _prompt_curve_max(message: str, default: float) -> float:
    value = cast(float, typer.prompt(message, default=default))
    if value < 1 or value > 2:
        raise typer.BadParameter("max multiplier must be between 1 and 2")
    return value


def _prompt_curve_power(message: str, default: float) -> float:
    value = cast(float, typer.prompt(message, default=default))
    if value <= 0:
        raise typer.BadParameter("curve power must be greater than 0")
    return value


PLANS: dict[str, PlanConfig] = {
    "production_methods": PlanConfig(
        plan=PRODUCTION_METHODS_PLAN,
        default_dir=MOD_ROOT / "common" / "production_methods",
        default_factor=PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
        title="Production Methods",
    ),
    "goods": PlanConfig(
        plan=GOODS_PLAN,
        default_dir=MOD_ROOT / "common" / "goods",
        default_factor=GOODS_COST_FACTOR,
        title="Goods",
    ),
    "pop_types": PlanConfig(
        plan=POP_TYPES_PLAN,
        text_plan=POP_TYPES_TEXT_PLAN,
        default_dir=MOD_ROOT / "common" / "pop_types",
        default_factor=1.0,
        title="Pop Types",
        uses_factor=False,
    ),
    "buy_packages": PlanConfig(
        plan=BUY_PACKAGES_PLAN,
        default_dir=MOD_ROOT / "common" / "buy_packages",
        default_factor=1.0,
        title="Buy Packages",
        uses_factor=False,
        context_builder=_buy_packages_context_builder,
    ),
}


def _resolve_backup_root() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return BACKUP_BASE_DIR / timestamp


def _backup_base_dir() -> Path:
    return BACKUP_BASE_DIR


def _list_backup_roots() -> list[Path]:
    base = _backup_base_dir()
    if not base.exists():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)


def _backup_file(source: Path, backup_root: Path) -> Path:
    source = source.resolve()
    try:
        rel_path = source.relative_to(MOD_ROOT)
    except ValueError:
        rel_path = Path(source.name)
    target = backup_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _baseline_base_dir() -> Path:
    return BASELINE_DATA_BASE_DIR


def _initialize_baseline_data() -> Path:
    baseline_root = _baseline_base_dir()
    if baseline_root.exists():
        return baseline_root

    baseline_root.mkdir(parents=True, exist_ok=True)
    for item in MOD_ROOT.iterdir():
        if not item.name in {"common"}:
            continue
        target = baseline_root / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    return baseline_root


def _baseline_path_for(source: Path, baseline_root: Path) -> Path:
    source = source.resolve()
    try:
        rel_path = source.relative_to(MOD_ROOT)
    except ValueError:
        rel_path = Path(source.name)
    return baseline_root / rel_path


def _ensure_baseline_file(source: Path, baseline_root: Path) -> Path:
    baseline_path = _baseline_path_for(source, baseline_root)
    if baseline_path.exists():
        return baseline_path
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, baseline_path)
    return baseline_path


def _select_plans(prompt: str) -> list[PlanConfig]:
    options = list(PLANS.keys())
    if _q_confirm("Apply ALL plans?", default=True):
        return [PLANS[k] for k in options]
    selection = _q_checkbox(prompt, choices=options)
    return [PLANS[k] for k in selection]


def _select_plan(prompt: str) -> PlanConfig:
    options = list(PLANS.keys())
    choice = _q_select(prompt, choices=options, default=options[0])
    return PLANS[choice]


def _select_files(directory: Path) -> list[Path]:
    directory = _resolve_user_path(directory)
    candidates = sorted(directory.rglob("*.txt"))
    if not candidates:
        raise typer.BadParameter(f"No files found under {directory}")
    if _q_confirm(f"Apply to ALL files under {directory}?", default=True):
        return candidates
    labels = [str(path.relative_to(directory)) for path in candidates]
    selection = _q_checkbox("Select files to edit", choices=labels)
    selected = set(selection)
    return [path for path, label in zip(candidates, labels) if label in selected]


def _apply_plan(
    config: PlanConfig,
    directory: Path,
    factor: float,
    files: list[Path],
    *,
    dry_run: bool,
    preserve: bool,
    backup_root: Path | None,   # NEW
    baseline_root: Path | None,
) -> Path | None:
    schema = generic_schema()
    header = (
        f"Plan: {config.title}\nDirectory: {directory}\nFiles: {len(files)}\n"
        f"Factor: {_format_factor(config, factor)}\nDry run: {dry_run}\nPreserve: {preserve}"
    )
    _console.print(Panel.fit(header, title="Apply", style="cyan"))

    for path in files:
        if baseline_root is None:
            text = path.read_text(encoding="utf-8")
        else:
            baseline_path = _ensure_baseline_file(path, baseline_root)
            text = baseline_path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        context = _context_for_document(config, document, factor)
        counts = _apply_edits(document, config.plan, context, dry_run=dry_run)
        total = sum(counts.values())
        if total == 0:
            continue

        if dry_run:
            _console.print(f"[yellow]Would update[/yellow] {path} ({total})")
            continue

        # Create the shared backup root lazily, but re-use it across plans
        if backup_root is None:
            backup_root = _resolve_backup_root()
            backup_root.mkdir(parents=True, exist_ok=True)
            _console.print(Panel.fit(str(backup_root), title="Backups", style="green"))

        _backup_file(path, backup_root)
        path.write_text(_format_document(document, preserve=preserve), encoding="utf-8")
        _console.print(f"[green]Updated[/green] {path} ({total})")

    return backup_root


def _apply_text_plan(
    config: PlanConfig,
    directory: Path,
    factor: float,
    files: list[Path],
    *,
    dry_run: bool,
    preserve: bool,
    backup_root: Path | None,
    baseline_root: Path | None,
) -> Path | None:
    _ = preserve
    if config.text_plan is None:
        return backup_root
    header = (
        f"Plan: {config.title}\nDirectory: {directory}\nFiles: {len(files)}\n"
        f"Factor: {_format_factor(config, factor)}\nDry run: {dry_run}\nPreserve: {preserve}"
    )
    _console.print(Panel.fit(header, title="Apply", style="cyan"))

    for path in files:
        if baseline_root is None:
            text = path.read_text(encoding="utf-8")
        else:
            baseline_path = _ensure_baseline_file(path, baseline_root)
            text = baseline_path.read_text(encoding="utf-8")
        updated, counts = _apply_text_edits(text, config.text_plan)
        total = sum(counts.values())
        if total == 0:
            continue

        if dry_run:
            _console.print(f"[yellow]Would update[/yellow] {path} ({total})")
            continue

        if backup_root is None:
            backup_root = _resolve_backup_root()
            backup_root.mkdir(parents=True, exist_ok=True)
            _console.print(Panel.fit(str(backup_root), title="Backups", style="green"))

        _backup_file(path, backup_root)
        path.write_text(updated, encoding="utf-8")
        _console.print(f"[green]Updated[/green] {path} ({total})")

    return backup_root


def _stats_plan(config: PlanConfig, directory: Path, factor: float) -> None:
    if config.text_plan is not None:
        _stats_text_plan(config, directory, factor)
        return
    schema = generic_schema()
    totals = {edit.name: 0 for edit in config.plan.edits}
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        context = _context_for_document(config, document, factor)
        counts = _apply_edits(document, config.plan, context, dry_run=True)
        for name, count in counts.items():
            totals[name] += count
    total = sum(totals.values())
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Matches", justify="right")
    for name, count in totals.items():
        table.add_row(name, str(count))
    table.add_row("Total", str(total), style="bold")
    header = (
        f"Plan: {config.title}\nDirectory: {directory}\n"
        f"Factor: {_format_factor(config, factor)}"
    )
    _console.print(Panel.fit(header, title="Stats", style="cyan"))
    _console.print(table)


def _stats_text_plan(config: PlanConfig, directory: Path, factor: float) -> None:
    if config.text_plan is None:
        return
    totals = {edit.name: 0 for edit in config.text_plan.edits}
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        _, counts = _apply_text_edits(text, config.text_plan)
        for name, count in counts.items():
            totals[name] += count
    total = sum(totals.values())
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Matches", justify="right")
    for name, count in totals.items():
        table.add_row(name, str(count))
    table.add_row("Total", str(total), style="bold")
    header = (
        f"Plan: {config.title}\nDirectory: {directory}\n"
        f"Factor: {_format_factor(config, factor)}"
    )
    _console.print(Panel.fit(header, title="Stats", style="cyan"))
    _console.print(table)


def _list_edits_plan(config: PlanConfig, factor: float) -> None:
    header = f"Plan: {config.title}\nFactor: {_format_factor(config, factor)}"
    _console.print(Panel.fit(header, title="Edit Plan", style="cyan"))
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Description")
    edits = config.text_plan.edits if config.text_plan is not None else config.plan.edits
    for edit in edits:
        table.add_row(edit.name, edit.description)
    _console.print(table)


def _echo_warn(message: str) -> None:
    _err_console.print(Panel.fit(message, title="Warning", style="yellow"))


@app.command()
def list_edits(
    plan: str | None = None,
    factor: float | None = None,
) -> None:
    config = PLANS.get(plan) if plan else _select_plan("Select a plan to list")
    if config is None:
        raise typer.BadParameter(f"Unknown plan '{plan}'")
    if factor is None:
        factor = config.default_factor
    _list_edits_plan(config, factor)


@app.command()
def apply(
    plan: str | None = None,
    directory: Path | None = None,
    factor: float | None = None,
    dry_run: bool = False,
    preserve: bool = True,
    baseline_data: bool = True,
) -> None:
    configs = [PLANS.get(plan)] if plan else _select_plans("Select plans to apply")
    if configs == [None]:
        raise typer.BadParameter(f"Unknown plan '{plan}'")

    backup_root: Path | None = None  # shared across all plans
    baseline_root = _initialize_baseline_data() if baseline_data else None

    for config in configs:
        if config is None:
            continue

        plan_directory = (
            _resolve_user_path(directory)
            if directory
            else _resolve_user_path(config.default_dir)
        )
        if directory is None:
            plan_directory = Path(typer.prompt("Directory to edit", default=str(plan_directory)))
            plan_directory = _resolve_user_path(plan_directory)

        plan_factor = factor
        if config.uses_factor:
            if plan_factor is None:
                plan_factor = cast(
                    float,
                    typer.prompt(
                        "Scale factor (multiply by)", default=config.default_factor
                    ),
                )
            if plan_factor == 0:
                raise typer.BadParameter("factor cannot be 0")
        else:
            plan_factor = config.default_factor

        plan_to_apply = config.plan
        text_plan_to_apply = config.text_plan
        curve_context_builder = config.context_builder
        if config.plan.name == "pop_types":
            selection = _q_checkbox(
                "Select pop_types edits",
                choices=["ALL", "only wage_weight", "only dependent_wage"],
            )
            wage_weight_factor = POP_TYPES_WAGE_WEIGHT_FACTOR
            dependent_wage_factor = POP_TYPES_DEPENDENT_WAGE_FACTOR
            if "ALL" in selection:
                plan_to_apply = config.plan
                wage_weight_factor = _prompt_scale(
                    "wage_weight factor (multiply by)",
                    POP_TYPES_WAGE_WEIGHT_FACTOR,
                )
                dependent_wage_factor = _prompt_scale(
                    "dependent_wage factor (multiply by)",
                    POP_TYPES_DEPENDENT_WAGE_FACTOR,
                )
            else:
                selected_names = set()
                if "only wage_weight" in selection:
                    selected_names.add("scale_wage_weight")
                    wage_weight_factor = _prompt_scale(
                        "wage_weight factor (multiply by)",
                        POP_TYPES_WAGE_WEIGHT_FACTOR,
                    )
                if "only dependent_wage" in selection:
                    selected_names.add("scale_dependent_wage")
                    dependent_wage_factor = _prompt_scale(
                        "dependent_wage factor (multiply by)",
                        POP_TYPES_DEPENDENT_WAGE_FACTOR,
                    )
                plan_to_apply = EditPlan(
                    name=config.plan.name,
                    edits=[
                        edit
                        for edit in config.plan.edits
                        if edit.name in selected_names
                    ],
                )
                if config.text_plan is not None:
                    text_plan_to_apply = TextEditPlan(
                        name=config.text_plan.name,
                        edits=[
                            edit
                            for edit in config.text_plan.edits
                            if edit.name in selected_names
                        ],
                    )
            if text_plan_to_apply is not None:
                text_plan_to_apply = _build_pop_types_text_plan_with_factors(
                    wage_weight_factor, dependent_wage_factor
                )
        if config.plan.name == "buy_packages":
            curve_max = _prompt_curve_max(
                "Max multiplier (<= 2x)", BUY_PACKAGES_CURVE_MAX
            )
            curve_power = _prompt_curve_power(
                "Curve power (higher = richer spend more)", BUY_PACKAGES_CURVE_POWER
            )
            curve_context_builder = _build_buy_packages_context_builder(
                curve_max, curve_power
            )

        files = _select_files(plan_directory)

        plan_config = PlanConfig(
            plan=plan_to_apply,
            text_plan=text_plan_to_apply,
            default_dir=config.default_dir,
            default_factor=config.default_factor,
            title=config.title,
            uses_factor=config.uses_factor,
            context_builder=curve_context_builder,
        )
        if plan_config.text_plan is not None:
            backup_root = _apply_text_plan(
                plan_config,
                plan_directory,
                plan_factor,
                files,
                dry_run=dry_run,
                preserve=preserve,
                backup_root=backup_root,
                baseline_root=baseline_root,
            )
        else:
            backup_root = _apply_plan(
                plan_config,
                plan_directory,
                plan_factor,
                files,
                dry_run=dry_run,
                preserve=preserve,
                backup_root=backup_root,  # PASS IT IN
                baseline_root=baseline_root,
            )



@app.command()
def stats(
    plan: str | None = None,
    directory: Path | None = None,
    factor: float | None = None,
) -> None:
    config = PLANS.get(plan) if plan else _select_plan("Select a plan to stats")
    if config is None:
        raise typer.BadParameter(f"Unknown plan '{plan}'")
    plan_directory = (
        _resolve_user_path(directory)
        if directory
        else _resolve_user_path(config.default_dir)
    )
    if config.uses_factor:
        plan_factor = factor if factor is not None else config.default_factor
    else:
        plan_factor = config.default_factor
    _stats_plan(config, plan_directory, plan_factor)


@app.command()
def restore(
    directory: Path | None = None,
    timestamp: str | None = None,
    dry_run: bool = False,
) -> None:
    backups = _list_backup_roots()
    baseline_root = _baseline_base_dir()
    has_baseline = baseline_root.exists()
    if not backups and not has_baseline:
        _echo_warn("No backups found.")
        return
    if timestamp is None:
        options = [p.name for p in backups]
        if has_baseline:
            options.insert(0, "baseline")
        timestamp = _q_select("Select a backup", choices=options, default=options[0])
    if timestamp == "baseline":
        if not has_baseline:
            raise typer.BadParameter("Baseline data not found.")
        backup_root = baseline_root
    else:
        backup_root = _backup_base_dir() / timestamp
        if not backup_root.exists():
            raise typer.BadParameter(f"Backup '{timestamp}' not found.")
    files = sorted(p for p in backup_root.rglob("*") if p.is_file())
    if not files:
        _echo_warn(f"No files found in backup '{timestamp}'.")
        return
    if not dry_run:
        if not _q_confirm(
            f"Restore {len(files)} files from {backup_root}?", default=False
        ):
            _echo_warn("Canceled.")
            return
    _console.print(
        Panel.fit(f"Restoring from {backup_root}", title="Restore", style="green")
    )
    restore_root = _resolve_user_path(directory) if directory else MOD_ROOT
    for backup_file in files:
        rel_path = backup_file.relative_to(backup_root)
        target = restore_root / rel_path
        if dry_run:
            _console.print(f"[yellow]Would restore[/yellow] {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, target)
        _console.print(f"[green]Restored[/green] {target}")


if __name__ == "__main__":
    app()
