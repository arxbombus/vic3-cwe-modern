from __future__ import annotations

from pathlib import Path

from cyclopts import App

from cwe_tools.paradox.files import expand_paths
from cwe_tools.paradox.localization import parse_localization
from cwe_tools.paradox.script import ParseError, parse_script

app = App(name="lint", help="Syntax-check Paradox script and localization files.")


@app.default
def lint_files(paths: list[Path]) -> None:
    """Parse files and report syntax errors."""
    errors: list[str] = []
    for path in expand_paths(paths):
        try:
            text = path.read_text(encoding="utf-8-sig")
            if path.suffix.lower() in {".yml", ".yaml"}:
                parse_localization(text)
            else:
                parse_script(text)
        except (OSError, ValueError, ParseError) as exc:
            errors.append(f"{path}: {exc}")
        else:
            print(f"ok {path}")
    if errors:
        raise SystemExit("\n".join(errors))
