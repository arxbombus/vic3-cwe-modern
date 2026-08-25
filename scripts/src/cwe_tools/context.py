from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RepoNotFoundError(RuntimeError):
    """Raised when the mod repository root cannot be found."""


@dataclass(frozen=True)
class RepoContext:
    root: Path
    scripts: Path

    @property
    def app_config(self) -> Path:
        return self.scripts / "app.toml"

    @property
    def manifests(self) -> Path:
        return self.scripts / "manifests"


def find_scripts_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "cwe_tools"
        ).is_dir():
            return candidate
        scripts = candidate / "scripts"
        if (scripts / "pyproject.toml").is_file() and (
            scripts / "src" / "cwe_tools"
        ).is_dir():
            return scripts
    raise RepoNotFoundError(f"Could not find scripts project from {current}")


def get_context(start: Path | None = None) -> RepoContext:
    scripts = find_scripts_root(start)
    root = scripts.parent
    return RepoContext(root=root, scripts=scripts)
