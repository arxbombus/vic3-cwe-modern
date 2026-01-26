from __future__ import annotations

from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from clausewitz import ClausewitzDocument
from clausewitz.io.save_document import SaveOptions
from clausewitz.model import Operator

from . import files
from .ops import (
    delete_entries,
    insert_entries_end_of_blocks,
    replace_values,
    scale_numeric_values,
)
from .schema import SchemaChoice, resolve_schema
from .cli_types import OperatorChoice, SaveMode
from .plans import list_plans, load_plan
from .plans.params import coerce_overrides, prompt_params, resolve_defaults
from . import ui
from .paths import MOD_ROOT
from .plans.registry import list_plan_ids

app = typer.Typer(no_args_is_help=True, pretty_exceptions_short=True)
_console = Console(stderr=True)
_err_console = Console(stderr=True)
plan_app = typer.Typer(no_args_is_help=True)
app.add_typer(plan_app, name="plan")


def _resolve_operator(value: OperatorChoice | None) -> Operator | None:
    if value is None:
        return None
    return value.value  # type: ignore[return-value]


def _resolve_files(
    paths: list[Path], *, pattern: str, prompt: bool, default_root: Path
) -> files.FileSelection:
    if prompt or not paths:
        selection = files.prompt_for_files(default_root=default_root, pattern=pattern, base_dir=MOD_ROOT)
        return selection
    return files.FileSelection(
        root=default_root,
        files=files.collect_files(paths, pattern=pattern, base_dir=MOD_ROOT),
    )


def _load_document(path: Path, schema_choice: SchemaChoice, root_key: str) -> ClausewitzDocument:
    schema = resolve_schema(schema_choice, root_key=root_key)
    text = path.read_text(encoding="utf-8")
    return ClausewitzDocument.from_text(text, schema=schema)


def _save_document(path: Path, document: ClausewitzDocument, mode: SaveMode) -> None:
    options = SaveOptions(mode=mode.value)
    document.save(path, mode=mode.value, options=options)


def _print_summary(*, title: str, files_total: int, files_changed: int, matches: int, dry_run: bool) -> None:
    header = f"Files: {files_total}\nChanged: {files_changed}\nMatches: {matches}\nDry run: {dry_run}"
    _console.print(Panel.fit(header, title=title, style="cyan"))


def _confirm_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        candidate = path if path.is_absolute() else (MOD_ROOT / path)
        if not candidate.exists():
            raise typer.BadParameter(f"Path not found: {candidate}")


def _parse_param_overrides(pairs: list[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if not pairs:
        return overrides
    for item in pairs:
        if "=" not in item:
            raise typer.BadParameter(f"Expected key=value, got '{item}'")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise typer.BadParameter(f"Expected key=value, got '{item}'")
        overrides[key] = value
    return overrides


def _select_plan_id(plan_id: str | None) -> str:
    if plan_id:
        return plan_id
    choices = list_plan_ids()
    if not choices:
        raise typer.BadParameter("No plans available.")
    return ui.select("Select a plan", choices=choices, default=choices[0])


@app.command()
def replace(
    key_pattern: str = typer.Argument(..., help="Key pattern to match (fnmatch or regex segments)"),
    new_raw: str = typer.Argument(..., help="Replacement raw value (text)"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    ancestor_suffix_pattern: str = typer.Option(
        "",
        "--ancestor",
        "-a",
        help="Ancestor path suffix pattern (e.g., **.building_modifiers).",
    ),
    exclude_key_patterns: list[str] | None = typer.Option(
        None,
        "--exclude",
        "-x",
        help="Exclude key patterns (repeatable).",
    ),
    operator: OperatorChoice | None = typer.Option(
        None,
        "--operator",
        "-o",
        help="Only match entries with this operator.",
    ),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.preserve, "--mode", help="Save mode."),
) -> None:
    paths = paths or []
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt, default_root=MOD_ROOT)
    total_matches = 0
    files_changed = 0
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        count = replace_values(
            doc,
            key_pattern=key_pattern,
            new_raw=new_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns or (),
            operator=_resolve_operator(operator),
        )
        if count > 0:
            total_matches += count
            files_changed += 1
            if not dry_run:
                _save_document(path, doc, mode)
                _console.print(f"[green]Updated[/green] {path} ({count})")
            else:
                _console.print(f"[yellow]Would update[/yellow] {path} ({count})")
    _print_summary(
        title="Replace",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=total_matches,
        dry_run=dry_run,
    )


@app.command()
def scale(
    key_pattern: str = typer.Argument(..., help="Key pattern to match (fnmatch or regex segments)"),
    factor: float = typer.Argument(..., help="Scale factor (multiply by)"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    ancestor_suffix_pattern: str = typer.Option(
        "",
        "--ancestor",
        "-a",
        help="Ancestor path suffix pattern (e.g., **.building_modifiers).",
    ),
    exclude_key_patterns: list[str] | None = typer.Option(
        None,
        "--exclude",
        "-x",
        help="Exclude key patterns (repeatable).",
    ),
    operator: OperatorChoice = typer.Option(
        OperatorChoice.eq,
        "--operator",
        "-o",
        help="Only match entries with this operator.",
    ),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.preserve, "--mode", help="Save mode."),
) -> None:
    if factor == 0:
        raise typer.BadParameter("factor cannot be 0")
    paths = paths or []
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt, default_root=MOD_ROOT)
    total_matches = 0
    files_changed = 0
    op = _resolve_operator(operator)
    if op is None:
        raise typer.BadParameter("operator is required for scale")
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        count = scale_numeric_values(
            doc,
            key_pattern=key_pattern,
            factor=factor,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns or (),
            operator=op,
        )
        if count > 0:
            total_matches += count
            files_changed += 1
            if not dry_run:
                _save_document(path, doc, mode)
                _console.print(f"[green]Updated[/green] {path} ({count})")
            else:
                _console.print(f"[yellow]Would update[/yellow] {path} ({count})")
    _print_summary(
        title="Scale",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=total_matches,
        dry_run=dry_run,
    )


@app.command()
def delete(
    key_pattern: str = typer.Argument(..., help="Key pattern to match (fnmatch or regex segments)"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    ancestor_suffix_pattern: str = typer.Option(
        "",
        "--ancestor",
        "-a",
        help="Ancestor path suffix pattern (e.g., **.building_modifiers).",
    ),
    exclude_key_patterns: list[str] | None = typer.Option(
        None,
        "--exclude",
        "-x",
        help="Exclude key patterns (repeatable).",
    ),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.preserve, "--mode", help="Save mode."),
) -> None:
    paths = paths or []
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt, default_root=MOD_ROOT)
    total_matches = 0
    files_changed = 0
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        count = delete_entries(
            doc,
            key_pattern=key_pattern,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns or (),
        )
        if count > 0:
            total_matches += count
            files_changed += 1
            if not dry_run:
                _save_document(path, doc, mode)
                _console.print(f"[green]Updated[/green] {path} ({count})")
            else:
                _console.print(f"[yellow]Would update[/yellow] {path} ({count})")
    _print_summary(
        title="Delete",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=total_matches,
        dry_run=dry_run,
    )


@app.command()
def insert(
    key_pattern: str = typer.Argument(..., help="Key pattern to match (fnmatch or regex segments)"),
    entry_raw: str = typer.Argument(..., help="Raw entry to insert (e.g., foo = 1)"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    ancestor_suffix_pattern: str = typer.Option(
        "",
        "--ancestor",
        "-a",
        help="Ancestor path suffix pattern (e.g., **.building_modifiers).",
    ),
    exclude_key_patterns: list[str] | None = typer.Option(
        None,
        "--exclude",
        "-x",
        help="Exclude key patterns (repeatable).",
    ),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.preserve, "--mode", help="Save mode."),
) -> None:
    paths = paths or []
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt, default_root=MOD_ROOT)
    total_matches = 0
    files_changed = 0
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        count = insert_entries_end_of_blocks(
            doc,
            key_pattern=key_pattern,
            entry_raw=entry_raw,
            ancestor_suffix_pattern=ancestor_suffix_pattern,
            exclude_key_patterns=exclude_key_patterns or (),
        )
        if count > 0:
            total_matches += count
            files_changed += 1
            if not dry_run:
                _save_document(path, doc, mode)
                _console.print(f"[green]Updated[/green] {path} ({count})")
            else:
                _console.print(f"[yellow]Would update[/yellow] {path} ({count})")
    _print_summary(
        title="Insert",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=total_matches,
        dry_run=dry_run,
    )


@app.command()
def format(
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to format (repeatable).",
    ),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.canonical, "--mode", help="Save mode."),
) -> None:
    paths = paths or []
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt, default_root=MOD_ROOT)
    files_changed = 0
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        files_changed += 1
        if not dry_run:
            _save_document(path, doc, mode)
            _console.print(f"[green]Formatted[/green] {path}")
        else:
            _console.print(f"[yellow]Would format[/yellow] {path}")
    _print_summary(
        title="Format",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=files_changed,
        dry_run=dry_run,
    )


@plan_app.command("list")
def plan_list() -> None:
    plans = list_plans()
    if not plans:
        raise typer.BadParameter("No plans available.")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Plan")
    table.add_column("Title")
    for plan in sorted(plans, key=lambda p: p.id):
        table.add_row(plan.id, plan.title)
    _console.print(table)


@plan_app.command("apply")
def plan_apply(
    plan_id: str | None = typer.Argument(None, help="Plan id"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    overrides: list[str] | None = typer.Option(
        None,
        "--set",
        "-s",
        help="Override plan param values (key=value).",
    ),
    prompt_params_flag: bool = typer.Option(
        True,
        "--prompt-params/--no-prompt-params",
        help="Prompt for plan parameters.",
    ),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt_files: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not write changes."),
    mode: SaveMode = typer.Option(SaveMode.preserve, "--mode", help="Save mode."),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
) -> None:
    selected_id = _select_plan_id(plan_id)
    plan = load_plan(selected_id)
    if plan is None:
        raise typer.BadParameter(f"Unknown plan '{selected_id}'")
    param_overrides = coerce_overrides(plan.params, _parse_param_overrides(overrides))
    values = (
        prompt_params(plan.params, param_overrides)
        if prompt_params_flag
        else resolve_defaults(plan.params, param_overrides)
    )
    execution = plan.build(values)
    paths = paths or plan.default_paths
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt_files, default_root=MOD_ROOT)

    totals = {edit.name: 0 for edit in execution.edits}
    files_changed = 0
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        result = execution.apply(doc)
        if result.total > 0:
            files_changed += 1
            if not dry_run:
                _save_document(path, doc, mode)
                _console.print(f"[green]Updated[/green] {path} ({result.total})")
            else:
                _console.print(f"[yellow]Would update[/yellow] {path} ({result.total})")
        for name, count in result.counts.items():
            totals[name] = totals.get(name, 0) + count

    _print_summary(
        title=f"Plan: {plan.title}",
        files_total=len(selection.files),
        files_changed=files_changed,
        matches=sum(totals.values()),
        dry_run=dry_run,
    )


@plan_app.command("stats")
def plan_stats(
    plan_id: str | None = typer.Argument(None, help="Plan id"),
    paths: list[Path] | None = typer.Option(
        None,
        "--path",
        "-p",
        help="File or directory to edit (repeatable).",
    ),
    overrides: list[str] | None = typer.Option(
        None,
        "--set",
        "-s",
        help="Override plan param values (key=value).",
    ),
    prompt_params_flag: bool = typer.Option(
        True,
        "--prompt-params/--no-prompt-params",
        help="Prompt for plan parameters.",
    ),
    pattern: str = typer.Option("*.txt", "--glob", "-g", help="Glob for directories."),
    prompt_files: bool = typer.Option(False, "--prompt", help="Select files interactively."),
    schema: SchemaChoice = typer.Option(
        SchemaChoice.generic,
        "--schema",
        help="Schema preset to use.",
    ),
    root_key: str = typer.Option("root", "--root-key", help="Root key for generic schema."),
) -> None:
    selected_id = _select_plan_id(plan_id)
    plan = load_plan(selected_id)
    if plan is None:
        raise typer.BadParameter(f"Unknown plan '{selected_id}'")
    param_overrides = coerce_overrides(plan.params, _parse_param_overrides(overrides))
    values = (
        prompt_params(plan.params, param_overrides)
        if prompt_params_flag
        else resolve_defaults(plan.params, param_overrides)
    )
    execution = plan.build(values)
    paths = paths or plan.default_paths
    _confirm_paths(paths)
    selection = _resolve_files(paths, pattern=pattern, prompt=prompt_files, default_root=MOD_ROOT)

    totals = {edit.name: 0 for edit in execution.edits}
    for path in selection.files:
        doc = _load_document(path, schema, root_key)
        result = execution.apply(doc)
        for name, count in result.counts.items():
            totals[name] = totals.get(name, 0) + count

    table = Table(show_header=True, header_style="bold")
    table.add_column("Edit")
    table.add_column("Matches", justify="right")
    for name, count in totals.items():
        table.add_row(name, str(count))
    table.add_row("Total", str(sum(totals.values())), style="bold")
    _console.print(Panel.fit(execution.describe(values), title=f"Plan: {plan.title}", style="cyan"))
    _console.print(table)


if __name__ == "__main__":
    app()
