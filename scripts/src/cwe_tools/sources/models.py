from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol


class FileSource(Protocol):
    """Minimal source interface used by generators."""

    def read_text(self, path: str | PurePosixPath) -> str: ...

    def list_files(
        self,
        directory: str | PurePosixPath,
        *,
        suffix: str | None = None,
    ) -> list[str]: ...
