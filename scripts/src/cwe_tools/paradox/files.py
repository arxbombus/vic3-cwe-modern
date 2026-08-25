from collections.abc import Iterable
from pathlib import Path

SCRIPT_SUFFIXES = {".txt", ".gui", ".asset"}
LOCALIZATION_SUFFIXES = {".yml", ".yaml"}
SUPPORTED_SUFFIXES = SCRIPT_SUFFIXES | LOCALIZATION_SUFFIXES


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    result: set[Path] = set()
    for path in paths:
        if path.is_file():
            result.add(path)
            continue
        if path.is_dir():
            result.update(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and candidate.suffix.lower() in SUPPORTED_SUFFIXES
            )
            continue
        raise FileNotFoundError(path)
    return sorted(result)
