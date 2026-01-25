from __future__ import annotations

from pathlib import Path


def find_mod_root(start: Path) -> Path:
    start = start.resolve()
    for path in [start] + list(start.parents):
        if (path / "common").exists() and (path / "scripts" / "pyproject.toml").exists():
            return path
    return start.parent.parent


MOD_ROOT = find_mod_root(Path(__file__))
SCRIPTS_ROOT = MOD_ROOT / "scripts"
BACKUP_BASE_DIR = SCRIPTS_ROOT / ".backups"
BASELINE_DATA_BASE_DIR = SCRIPTS_ROOT / ".baseline_data"
