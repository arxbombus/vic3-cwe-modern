from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Callable, Iterable, cast

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clausewitz import ClausewitzFormatter, ClausewitzParser, DocumentSchema, KeyRule, ClausewitzDocument
from clausewitz.nodes import ClausewitzBlock, ClausewitzEntry, ClausewitzList


app = typer.Typer(no_args_is_help=True)
_console = Console()
_err_console = Console(stderr=True)


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


def _format_document(document:ClausewitzDocument) -> str:
    formatter = ClausewitzFormatter()
    lines: list[str] = []
    for entry in document.entries():
        lines.extend(formatter.format_entry(entry.key, entry.value, 0))
    return "\n".join(lines) + "\n"


def _build_production_method_plan() -> EditPlan:
    def is_building_employment(path: tuple[str, ...], entry: ClausewitzEntry) -> bool:
        if not _in_building_level_scaled(path):
            return False
        key = str(entry.key)
        return (
            key.startswith("building_employment_")
            and key.endswith("_add")
            and isinstance(entry.value, (int, float))
        )

    def scale_entry(entry: ClausewitzEntry, context: EditContext) -> None:
        if not isinstance(entry.value, (int, float)):
            raise ValueError("Expected numeric value for scaling")
        if context.factor == 0:
            raise ValueError("Scaling factor cannot be 0")
        entry.value = int(entry.value * context.factor)

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


def _resolve_backup_root() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "backups" / timestamp


def _backup_base_dir() -> Path:
    return Path(__file__).resolve().parent / "backups"


def _list_backup_roots() -> list[Path]:
    base = _backup_base_dir()
    if not base.exists():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)


def _backup_file(source: Path, directory: Path, backup_root: Path) -> Path:
    try:
        rel_path = source.relative_to(directory)
    except ValueError:
        rel_path = Path(source.name)
    target = backup_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _echo_info(message: str) -> None:
    _console.print(message)


def _echo_warn(message: str) -> None:
    _err_console.print(Panel.fit(message, title="Warning", style="yellow"))


def _echo_success(message: str) -> None:
    _console.print(Panel.fit(message, title="Success", style="green"))


@app.command()
def list_edits(factor: float = PRODUCTION_METHODS_EMPLOYMENT_FACTOR) -> None:
    header = f"Plan: {PRODUCTION_METHODS_PLAN.name}\nFactor: {factor}"
    _console.print(Panel.fit(header, title="Edit Plan", style="cyan"))
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Description")
    for edit in PRODUCTION_METHODS_PLAN.edits:
        table.add_row(edit.name, edit.description)
    _console.print(table)


@app.command()
def apply(
    directory: Path = Path("../common/production_methods"),
    factor: float = PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
    dry_run: bool = False,
) -> None:
    schema = generic_schema()
    context = EditContext(factor=factor)
    backup_root: Path | None = None
    header = f"Directory: {directory}\nFactor: {factor}\nDry run: {dry_run}"
    _console.print(Panel.fit(header, title="Apply", style="cyan"))
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        counts = _apply_edits(document, PRODUCTION_METHODS_PLAN, context, dry_run=dry_run)
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
        path.write_text(_format_document(document), encoding="utf-8")
        _console.print(f"[green]Updated[/green] {path} ({total})")


@app.command()
def stats(
    directory: Path = Path("../common/production_methods"),
    factor: float = PRODUCTION_METHODS_EMPLOYMENT_FACTOR,
) -> None:
    schema = generic_schema()
    context = EditContext(factor=factor)
    totals = {edit.name: 0 for edit in PRODUCTION_METHODS_PLAN.edits}
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        counts = _apply_edits(document, PRODUCTION_METHODS_PLAN, context, dry_run=True)
        for name, count in counts.items():
            totals[name] += count
    total = sum(totals.values())
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Matches", justify="right")
    for name, count in totals.items():
        table.add_row(name, str(count))
    table.add_row("Total", str(total), style="bold")
    _console.print(Panel.fit(f"Directory: {directory}\nFactor: {factor}", title="Stats", style="cyan"))
    _console.print(table)


@app.command()
def tweak(
    directory: Path = Path("../common/production_methods"),
    factor: float | None = None,
    dry_run: bool = False,
) -> None:
    if factor is None:
        factor = cast(float, typer.prompt("Employment scale factor (multiply by)", default=PRODUCTION_METHODS_EMPLOYMENT_FACTOR))
    if factor == 0:
        raise typer.BadParameter("factor cannot be 0")
    if not dry_run:
        if not typer.confirm(f"Apply edits with factor {factor}?", default=False):
            _echo_warn("Canceled.")
            return
    apply(directory=directory, factor=factor, dry_run=dry_run)


@app.command()
def restore(
    directory: Path = Path("../common/production_methods"),
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
    for backup_file in files:
        rel_path = backup_file.relative_to(backup_root)
        target = directory / rel_path
        if dry_run:
            _console.print(f"[yellow]Would restore[/yellow] {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, target)
        _console.print(f"[green]Restored[/green] {target}")


if __name__ == "__main__":
    app()
