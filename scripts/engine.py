from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil

from plan_api import ApplyResult, ExecutionPlan


@dataclass(frozen=True)
class EnginePaths:
    mod_root: Path
    backup_base_dir: Path
    baseline_base_dir: Path


@dataclass(frozen=True)
class FileResult:
    path: Path
    result: ApplyResult
    changed: bool


@dataclass(frozen=True)
class ApplySummary:
    backup_root: Path | None
    results: list[FileResult]


def resolve_user_path(paths: EnginePaths, target: Path) -> Path:
    return target.resolve() if target.is_absolute() else (paths.mod_root / target).resolve()


def resolve_backup_root(paths: EnginePaths) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return paths.backup_base_dir / timestamp


def list_backup_roots(paths: EnginePaths) -> list[Path]:
    base = paths.backup_base_dir
    if not base.exists():
        return []
    return sorted((path for path in base.iterdir() if path.is_dir()), reverse=True)


def backup_file(paths: EnginePaths, source: Path, backup_root: Path) -> Path:
    source = source.resolve()
    try:
        rel_path = source.relative_to(paths.mod_root)
    except ValueError:
        rel_path = Path(source.name)
    target = backup_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def initialize_baseline_data(paths: EnginePaths) -> Path:
    baseline_root = paths.baseline_base_dir
    if baseline_root.exists():
        return baseline_root

    baseline_root.mkdir(parents=True, exist_ok=True)
    for item in paths.mod_root.iterdir():
        if item.name != "common":
            continue
        target = baseline_root / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    return baseline_root


def baseline_path_for(paths: EnginePaths, source: Path, baseline_root: Path) -> Path:
    source = source.resolve()
    try:
        rel_path = source.relative_to(paths.mod_root)
    except ValueError:
        rel_path = Path(source.name)
    return baseline_root / rel_path


def ensure_baseline_file(paths: EnginePaths, source: Path, baseline_root: Path) -> Path:
    baseline_path = baseline_path_for(paths, source, baseline_root)
    if baseline_path.exists():
        return baseline_path
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, baseline_path)
    return baseline_path


def apply_to_files(
    plan: ExecutionPlan,
    files: list[Path],
    *,
    dry_run: bool,
    preserve: bool,
    backup_root: Path | None,
    baseline_root: Path | None,
    paths: EnginePaths,
) -> ApplySummary:
    results: list[FileResult] = []
    for path in files:
        if baseline_root is None:
            text = path.read_text(encoding="utf-8")
        else:
            baseline_path = ensure_baseline_file(paths, path, baseline_root)
            text = baseline_path.read_text(encoding="utf-8")

        result = plan.apply_text(text, path, preserve)
        total = sum(result.counts.values())
        changed = result.updated_text is not None and total > 0

        if changed and not dry_run:
            if backup_root is None:
                backup_root = resolve_backup_root(paths)
                backup_root.mkdir(parents=True, exist_ok=True)
            backup_file(paths, path, backup_root)
            path.write_text(result.updated_text, encoding="utf-8")

        results.append(FileResult(path=path, result=result, changed=changed))

    return ApplySummary(backup_root=backup_root, results=results)
