from __future__ import annotations

from pathlib import Path
from typing import Any

import shutil
import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import engine
import plan_loader
import ui
from paths import BACKUP_BASE_DIR, BASELINE_DATA_BASE_DIR, MOD_ROOT, SCRIPTS_ROOT


app = typer.Typer(no_args_is_help=True, pretty_exceptions_short=True)
_console = Console(stderr=True)
_err_console = Console(stderr=True)

ENGINE_PATHS = engine.EnginePaths(
    mod_root=MOD_ROOT,
    backup_base_dir=BACKUP_BASE_DIR,
    baseline_base_dir=BASELINE_DATA_BASE_DIR,
)

if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

PLANS = plan_loader.load_plans(
    [
        ("plans_builtin", SCRIPTS_ROOT / "plans_builtin"),
        ("plans_user", SCRIPTS_ROOT / "plans_user"),
    ]
)


def _select_plans(prompt: str) -> list[str]:
    options = sorted(PLANS.keys())
    if not options:
        raise typer.BadParameter("No plans available.")
    if ui.confirm("Apply ALL plans?", default=True):
        return options
    selection = ui.multiselect(prompt, choices=options)
    if not selection:
        raise typer.Abort()
    return [plan_id for plan_id in options if plan_id in selection]


def _select_plan(prompt: str) -> str:
    options = sorted(PLANS.keys())
    if not options:
        raise typer.BadParameter("No plans available.")
    choice = ui.select(prompt, choices=options, default=options[0])
    return choice


def _select_files(directory: Path) -> list[Path]:
    candidates = sorted(directory.rglob("*.txt"))
    if not candidates:
        raise typer.BadParameter(f"No files found under {directory}")
    if ui.confirm(f"Apply to ALL files under {directory}?", default=True):
        return candidates
    labels = [str(path.relative_to(directory)) for path in candidates]
    selection = ui.multiselect("Select files to edit", choices=labels)
    if not selection:
        raise typer.Abort()
    selected = set(selection)
    return [path for path, label in zip(candidates, labels) if label in selected]


def _param_overrides(plan_params: list, factor: float | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if factor is None:
        return overrides
    names = {param.name for param in plan_params}
    if "factor" in names:
        overrides["factor"] = factor
    elif "employment_factor" in names:
        overrides["employment_factor"] = factor
    return overrides


def _echo_warn(message: str) -> None:
    _err_console.print(Panel.fit(message, title="Warning", style="yellow"))


@app.command()
def list_edits(
    plan: str | None = None,
    factor: float | None = None,
) -> None:
    plan_id = plan or _select_plan("Select a plan to list")
    plan_spec = PLANS.get(plan_id)
    if plan_spec is None:
        raise typer.BadParameter(f"Unknown plan '{plan_id}'")
    overrides = _param_overrides(plan_spec.params, factor)
    values = ui.resolve_defaults(plan_spec.params, overrides)
    execution = plan_spec.build(values)
    header = f"Plan: {plan_spec.title}\n{execution.describe(values)}"
    _console.print(Panel.fit(header, title="Edit Plan", style="cyan"))
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Description")
    for edit in execution.edits:
        table.add_row(edit.name, edit.description)
    _console.print(table)


@app.command()
def apply(
    plan: str | None = None,
    directory: Path | None = None,
    factor: float | None = None,
    dry_run: bool = False,
    preserve: bool = True,
    baseline_data: bool = True,
) -> None:
    plan_ids = [plan] if plan else _select_plans("Select plans to apply")
    if plan_ids == [None]:
        raise typer.BadParameter(f"Unknown plan '{plan}'")

    backup_root: Path | None = None
    baseline_root = engine.initialize_baseline_data(ENGINE_PATHS) if baseline_data else None

    for plan_id in plan_ids:
        plan_spec = PLANS.get(plan_id)
        if plan_spec is None:
            raise typer.BadParameter(f"Unknown plan '{plan_id}'")

        plan_directory = (
            engine.resolve_user_path(ENGINE_PATHS, directory)
            if directory
            else engine.resolve_user_path(ENGINE_PATHS, plan_spec.default_dir)
        )
        if directory is None:
            plan_directory = ui.path("Directory to edit", default=plan_directory)
            plan_directory = engine.resolve_user_path(ENGINE_PATHS, plan_directory)

        overrides = _param_overrides(plan_spec.params, factor)
        values = ui.prompt_form(plan_spec.params, overrides)
        execution = plan_spec.build(values)

        files = _select_files(plan_directory)
        header = (
            f"Plan: {plan_spec.title}\n{execution.describe(values)}\nDirectory: {plan_directory}\n"
            f"Files: {len(files)}\nDry run: {dry_run}\nPreserve: {preserve}"
        )
        _console.print(Panel.fit(header, title="Apply", style="cyan"))

        summary = engine.apply_to_files(
            execution,
            files,
            dry_run=dry_run,
            preserve=preserve,
            backup_root=backup_root,
            baseline_root=baseline_root,
            paths=ENGINE_PATHS,
        )

        if backup_root is None and summary.backup_root is not None:
            _console.print(Panel.fit(str(summary.backup_root), title="Backups", style="green"))
        backup_root = summary.backup_root

        for result in summary.results:
            total = sum(result.result.counts.values())
            if total == 0:
                continue
            if dry_run:
                _console.print(f"[yellow]Would update[/yellow] {result.path} ({total})")
            else:
                _console.print(f"[green]Updated[/green] {result.path} ({total})")


@app.command()
def stats(
    plan: str | None = None,
    directory: Path | None = None,
    factor: float | None = None,
) -> None:
    plan_id = plan or _select_plan("Select a plan to stats")
    plan_spec = PLANS.get(plan_id)
    if plan_spec is None:
        raise typer.BadParameter(f"Unknown plan '{plan_id}'")

    plan_directory = (
        engine.resolve_user_path(ENGINE_PATHS, directory)
        if directory
        else engine.resolve_user_path(ENGINE_PATHS, plan_spec.default_dir)
    )
    overrides = _param_overrides(plan_spec.params, factor)
    values = ui.resolve_defaults(plan_spec.params, overrides)
    execution = plan_spec.build(values)

    files = sorted(plan_directory.rglob("*.txt"))
    if not files:
        raise typer.BadParameter(f"No files found under {plan_directory}")

    summary = engine.apply_to_files(
        execution,
        files,
        dry_run=True,
        preserve=True,
        backup_root=None,
        baseline_root=None,
        paths=ENGINE_PATHS,
    )

    totals = {edit.name: 0 for edit in execution.edits}
    for result in summary.results:
        for name, count in result.result.counts.items():
            totals[name] = totals.get(name, 0) + count
    total = sum(totals.values())
    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Matches", justify="right")
    for name, count in totals.items():
        table.add_row(name, str(count))
    table.add_row("Total", str(total), style="bold")
    header = f"Plan: {plan_spec.title}\n{execution.describe(values)}\nDirectory: {plan_directory}"
    _console.print(Panel.fit(header, title="Stats", style="cyan"))
    _console.print(table)


@app.command()
def restore(
    directory: Path | None = None,
    timestamp: str | None = None,
    dry_run: bool = False,
) -> None:
    backups = engine.list_backup_roots(ENGINE_PATHS)
    baseline_root = ENGINE_PATHS.baseline_base_dir
    has_baseline = baseline_root.exists()
    if not backups and not has_baseline:
        _echo_warn("No backups found.")
        return
    if timestamp is None:
        options = [p.name for p in backups]
        if has_baseline:
            options.insert(0, "baseline")
        timestamp = ui.select("Select a backup", choices=options, default=options[0])
    if timestamp == "baseline":
        if not has_baseline:
            raise typer.BadParameter("Baseline data not found.")
        backup_root = baseline_root
    else:
        backup_root = ENGINE_PATHS.backup_base_dir / timestamp
        if not backup_root.exists():
            raise typer.BadParameter(f"Backup '{timestamp}' not found.")
    files = sorted(p for p in backup_root.rglob("*") if p.is_file())
    if not files:
        _echo_warn(f"No files found in backup '{timestamp}'.")
        return
    if not dry_run:
        if not ui.confirm(f"Restore {len(files)} files from {backup_root}?", default=False):
            _echo_warn("Canceled.")
            return
    _console.print(Panel.fit(f"Restoring from {backup_root}", title="Restore", style="green"))
    restore_root = engine.resolve_user_path(ENGINE_PATHS, directory) if directory else MOD_ROOT
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
