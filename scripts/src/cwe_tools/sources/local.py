from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class LocalSource:
    root: Path

    def _path(self, path: str | PurePosixPath) -> Path:
        relative = Path(*PurePosixPath(str(path)).parts)
        return (self.root / relative).resolve()

    def read_text(self, path: str | PurePosixPath) -> str:
        return self._path(path).read_text(encoding="utf-8-sig")

    def list_files(
        self,
        directory: str | PurePosixPath,
        *,
        suffix: str | None = None,
    ) -> list[str]:
        base = self._path(directory)
        if not base.exists():
            return []
        files = [p for p in base.iterdir() if p.is_file()]
        if suffix is not None:
            files = [p for p in files if p.suffix == suffix]
        return sorted(p.relative_to(self.root).as_posix() for p in files)
