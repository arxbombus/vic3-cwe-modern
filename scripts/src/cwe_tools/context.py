from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RepoNotFoundError(RuntimeError):
    """Raised when the CWE repository root cannot be found."""


@dataclass(frozen=True)
class RepoContext:
    root: Path

    @property
    def scripts(self) -> Path:
        return self.root / "scripts"

    @property
    def manifests(self) -> Path:
        return self.scripts / "manifests"

    @property
    def common(self) -> Path:
        return self.root / "common"

    @property
    def localization(self) -> Path:
        return self.root / "localization"

    @property
    def gfx(self) -> Path:
        return self.root / "gfx"


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()

    for candidate in (current, *current.parents):
        if _is_repo_root(candidate):
            return candidate

    raise RepoNotFoundError(f"Could not find CWE repository root from {current}")


def _is_repo_root(path: Path) -> bool:
    return (path / "scripts" / "pyproject.toml").is_file() and (
        path / "common"
    ).is_dir()


def get_context() -> RepoContext:
    return RepoContext(root=find_repo_root())
