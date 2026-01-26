from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from . import ui


@dataclass(frozen=True)
class FileSelection:
    root: Path
    files: list[Path]


def collect_files(paths: list[Path], *, pattern: str, base_dir: Path | None = None) -> list[Path]:
    results: list[Path] = []
    for raw in paths:
        path = raw.expanduser()
        if base_dir is not None and not path.is_absolute():
            path = (base_dir / path).resolve()
        if path.is_dir():
            results.extend(sorted(path.rglob(pattern)))
        elif path.is_file():
            results.append(path)
        else:
            raise typer.BadParameter(f"Path not found: {path}")
    if not results:
        raise typer.BadParameter("No files found.")
    return _dedupe_paths(results)


def prompt_for_files(*, default_root: Path, pattern: str, base_dir: Path | None = None) -> FileSelection:
    root = ui.path("Directory to edit", default=default_root)
    root = root.expanduser()
    if base_dir is not None and not root.is_absolute():
        root = (base_dir / root).resolve()
    if not root.exists():
        raise typer.BadParameter(f"Directory not found: {root}")
    pattern_value = ui.text("Glob pattern", default=pattern)
    candidates = sorted(root.rglob(pattern_value))
    if not candidates:
        raise typer.BadParameter(f"No files found under {root} with {pattern_value}")
    if ui.confirm(f"Use all {len(candidates)} files?", default=True):
        return FileSelection(root=root, files=candidates)
    labels = [str(path.relative_to(root)) for path in candidates]
    selection = ui.multiselect("Select files", choices=labels)
    if not selection:
        raise typer.Abort()
    selected = [path for path, label in zip(candidates, labels) if label in selection]
    return FileSelection(root=root, files=selected)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out
