from __future__ import annotations

from pathlib import Path

from cyclopts import App

from cwe_tools.paradox.files import expand_paths
from cwe_tools.paradox.localization import format_localization, parse_localization
from cwe_tools.paradox.script import format_script, parse_script

app = App(name="format", help="Format Paradox script or Victoria 3 localization files.")


def _format_path(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yml", ".yaml"}:
        return format_localization(parse_localization(text))
    return format_script(parse_script(text))


@app.default
def format_files(paths: list[Path], *, check: bool = False) -> None:
    """Format files in place, or fail if --check finds stale formatting."""
    stale: list[Path] = []
    for path in expand_paths(paths):
        formatted = _format_path(path)
        actual = path.read_text(encoding="utf-8")
        if actual == formatted:
            continue
        if check:
            stale.append(path)
        else:
            path.write_text(formatted, encoding="utf-8")
            print(f"formatted {path}")
    if stale:
        raise SystemExit(
            "Formatting required:\n" + "\n".join(str(path) for path in stale)
        )
