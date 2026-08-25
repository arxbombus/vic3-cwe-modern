from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class LocalizationEntry:
    key: str
    value: str
    version: int | None = None


@dataclass
class LocalizationComment:
    text: str


LocalizationItem = LocalizationEntry | LocalizationComment


@dataclass
class LocalizationFile:
    language: str
    items: list[LocalizationItem] = field(default_factory=list)


_ENTRY_RE = re.compile(r'^\s*([A-Za-z0-9_.$@\-]+):(?:(\d+))?\s+"((?:\\.|[^"\\])*)"\s*$')


def parse_localization(text: str) -> LocalizationFile:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        raise ValueError("Empty localization file")

    header = lines[0].strip()
    if not header.endswith(":") or not header.startswith("l_"):
        raise ValueError("Localization file must start with an l_<language>: header")
    result = LocalizationFile(language=header[:-1])

    for line_number, line in enumerate(lines[1:], start=2):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            result.items.append(LocalizationComment(stripped[1:].lstrip()))
            continue
        match = _ENTRY_RE.match(line)
        if match is None:
            raise ValueError(
                f"Invalid localization entry on line {line_number}: {line}"
            )
        result.items.append(
            LocalizationEntry(
                key=match.group(1),
                version=int(match.group(2)) if match.group(2) else None,
                value=match.group(3),
            )
        )
    return result
