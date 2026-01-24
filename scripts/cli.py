from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Callable, Iterable, cast

import questionary
from prompt_toolkit.styles import Style
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clausewitz import ClausewitzFormatter, ClausewitzParser, DocumentSchema, KeyRule, ClausewitzDocument
from clausewitz.nodes import ClausewitzBlock, ClausewitzEntry, ClausewitzList, ClausewitzScalarValue


app = typer.Typer(no_args_is_help=True)
_console = Console()
_err_console = Console(stderr=True)
_prompt_style = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:cyan bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "reverse"),
        ("selected", "fg:salmon"),
        ("separator", "fg:cyan"),
        ("instruction", "fg:cyan"),
        ("text", ""),
    ]
)


def generic_schema() -> DocumentSchema:
    root = KeyRule(name="root", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=True))
    return DocumentSchema(name="generic", root_key="root", root_rule=root)


@dataclass(frozen=True)
class EditRule:
    name: str
    description: str
    predicate: Callable[[tuple[str, ...], ClausewitzEntry], bool]
    apply: Callable[[ClausewitzEntry, "EditContext"], None]


@dataclass(frozen=True)
class EditPlan:
    name: str
    edits: list[EditRule]


@dataclass(frozen=True)
class EditContext:
    factor: float


@dataclass(frozen=True)
class PlanConfig:
    plan: EditPlan
    default_dir: Path
    default_factor: float
    title: str


def _iter_entries(block: ClausewitzBlock, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], ClausewitzEntry]]:
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
    return len(path) >= 3 and path[-3] == "building_modifiers" and path[-2] == "level_scaled"


def _apply_edits(document:ClausewitzDocument, plan: EditPlan, context: EditContext, dry_run: bool) -> dict[str, int]:
    counts = {edit.name: 0 for edit in plan.edits}
    for path, entry in _iter_entries(document.root):
        for edit in plan.edits:
            if edit.predicate(path, entry):
                counts[edit.name] += 1
                if not dry_run:
                    edit.apply(entry, context)
    return counts


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

    def scale_entry(entry: ClausewitzEntry, context: EditContext) -> None:
        if not isinstance(entry.value, ClausewitzScalarValue):
            raise ValueError("Expected scalar value for scaling")
        if not isinstance(entry.value.value, (int, float)):
            raise ValueError("Expected numeric value for scaling")
        if context.factor == 0:
            raise ValueError("Scaling factor cannot be 0")
        scaled = entry.value.value * context.factor
        entry.value.value = int(scaled) if isinstance(entry.value.value, int) else scaled
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

PRODUCTION_METHODS_PLAN = _build_production_method_plan()
PRODUCTION_METHODS_EMPLOYMENT_FACTOR = 2.0


def _build_goods_plan() -> EditPlan:
    def is_goods_cost(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        return (
            entry.key == "cost"
            and isinstance(entry.value, ClausewitzScalarValue)
            and isinstance(entry.value.value, (int, float))
        )

    def scale_cost(entry: ClausewitzEntry, context: EditContext) -> None:
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


GOODS_PLAN = _build_goods_plan()
GOODS_COST_FACTOR = 1.5

PLANS: dict[str, PlanConfig] = {
    "production_methods": PlanConfig(
        plan=PRODUCTION_METHODS_PLAN,
        default_dir=Path("../common/production_methods"),
        default_factor=PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
        title="Production Methods",
    ),
    "goods": PlanConfig(
        plan=GOODS_PLAN,
        default_dir=Path("../common/goods"),
        default_factor=GOODS_COST_FACTOR,
        title="Goods",
    ),
}


def _resolve_backup_root() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "backups" / timestamp


def _mod_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _backup_base_dir() -> Path:
    return Path(__file__).resolve().parent / "backups"


def _list_backup_roots() -> list[Path]:
    base = _backup_base_dir()
    if not base.exists():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)


def _backup_file(source: Path, directory: Path, backup_root: Path) -> Path:
    try:
        rel_path = source.relative_to(_mod_root())
    except ValueError:
        try:
            rel_path = source.relative_to(directory)
        except ValueError:
            rel_path = Path(source.name)
    target = backup_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _select_plan(prompt: str) -> PlanConfig:
    options = list(PLANS.keys())
    choice = questionary.select(
        prompt,
        choices=options,
        default=options[0],
        style=_prompt_style,
    ).ask()
    if choice is None:
        raise typer.Abort()
    return PLANS[choice]


def _select_files(directory: Path) -> list[Path]:
    candidates = sorted(directory.rglob("*.txt"))
    if not candidates:
        raise typer.BadParameter(f"No files found under {directory}")
    labels = [str(path.relative_to(directory)) for path in candidates]
    choices = ["<ALL FILES>"] + labels
    selection = questionary.checkbox(
        "Select files to edit",
        choices=choices,
        style=_prompt_style,
    ).ask()
    if not selection:
        raise typer.Abort()
    if "<ALL FILES>" in selection:
        return candidates
    selected = {item for item in selection}
    return [path for path, label in zip(candidates, labels) if label in selected]


def _apply_plan(
    config: PlanConfig,
    directory: Path,
    factor: float,
    files: list[Path],
    *,
    dry_run: bool,
    preserve: bool,
) -> None:
    schema = generic_schema()
    context = EditContext(factor=factor)
    backup_root: Path | None = None
    header = (
        f"Plan: {config.title}\nDirectory: {directory}\nFiles: {len(files)}\n"
        f"Factor: {factor}\nDry run: {dry_run}\nPreserve: {preserve}"
    )
    _console.print(Panel.fit(header, title="Apply", style="cyan"))
    for path in files:
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        counts = _apply_edits(document, config.plan, context, dry_run=dry_run)
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
        _backup_file(path, directory, backup_root)
        path.write_text(_format_document(document, preserve=preserve), encoding="utf-8")
        _console.print(f"[green]Updated[/green] {path} ({total})")


def _stats_plan(config: PlanConfig, directory: Path, factor: float) -> None:
    schema = generic_schema()
    context = EditContext(factor=factor)
    totals = {edit.name: 0 for edit in config.plan.edits}
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
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
    header = f"Plan: {config.title}\nDirectory: {directory}\nFactor: {factor}"
    _console.print(Panel.fit(header, title="Stats", style="cyan"))
    _console.print(table)


def _list_edits_plan(config: PlanConfig, factor: float) -> None:
    header = f"Plan: {config.title}\nFactor: {factor}"
    _console.print(Panel.fit(header, title="Edit Plan", style="cyan"))
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Description")
    for edit in config.plan.edits:
        table.add_row(edit.name, edit.description)
    _console.print(table)


def _echo_info(message: str) -> None:
    _console.print(message)


def _echo_warn(message: str) -> None:
    _err_console.print(Panel.fit(message, title="Warning", style="yellow"))


def _echo_success(message: str) -> None:
    _console.print(Panel.fit(message, title="Success", style="green"))


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
) -> None:
    config = PLANS.get(plan) if plan else _select_plan("Select a plan to apply")
    if config is None:
        raise typer.BadParameter(f"Unknown plan '{plan}'")
    if directory is None:
        directory = config.default_dir
    if factor is None:
        factor = cast(float, typer.prompt("Scale factor (multiply by)", default=config.default_factor))
    if factor == 0:
        raise typer.BadParameter("factor cannot be 0")
    files = _select_files(directory)
    _apply_plan(config, directory, factor, files, dry_run=dry_run, preserve=preserve)


@app.command()
def stats(
    plan: str | None = None,
    directory: Path | None = None,
    factor: float | None = None,
) -> None:
    config = PLANS.get(plan) if plan else _select_plan("Select a plan to stats")
    if config is None:
        raise typer.BadParameter(f"Unknown plan '{plan}'")
    if directory is None:
        directory = config.default_dir
    if factor is None:
        factor = config.default_factor
    _stats_plan(config, directory, factor)


@app.command()
@app.command()
def restore(
    directory: Path | None = None,
    timestamp: str | None = None,
    dry_run: bool = False,
) -> None:
    backups = _list_backup_roots()
    if not backups:
        _echo_warn("No backups found.")
        return
    if timestamp is None:
        options = [p.name for p in backups]
        timestamp = questionary.select(
            "Select a backup",
            choices=options,
            default=options[0],
            style=_prompt_style,
        ).ask()
        if timestamp is None:
            _echo_warn("Canceled.")
            return
    backup_root = _backup_base_dir() / timestamp
    if not backup_root.exists():
        raise typer.BadParameter(f"Backup '{timestamp}' not found.")
    files = sorted(p for p in backup_root.rglob("*") if p.is_file())
    if not files:
        _echo_warn(f"No files found in backup '{timestamp}'.")
        return
    if not dry_run:
        if not typer.confirm(f"Restore {len(files)} files from {backup_root}?", default=False):
            _echo_warn("Canceled.")
            return
    _console.print(Panel.fit(f"Restoring from {backup_root}", title="Restore", style="green"))
    restore_root = (directory or _mod_root()).resolve()
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
