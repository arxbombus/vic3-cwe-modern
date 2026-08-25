from __future__ import annotations

from cwe_tools.paradox.localization.parser import (
    LocalizationComment,
    LocalizationEntry,
    LocalizationFile,
)


def format_localization(document: LocalizationFile) -> str:
    lines = [f"{document.language}:"]
    for item in document.items:
        if isinstance(item, LocalizationComment):
            lines.append(f"  # {item.text}".rstrip())
            continue
        assert isinstance(item, LocalizationEntry)
        version = str(item.version) if item.version is not None else ""
        lines.append(f'  {item.key}:{version} "{item.value}"')
    # Victoria 3 localization expects UTF-8 with BOM. Returning the BOM as a
    # codepoint keeps callers simple when they write with encoding="utf-8".
    return "\ufeff" + "\n".join(lines).rstrip() + "\n"
