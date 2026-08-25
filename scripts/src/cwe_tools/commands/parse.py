from __future__ import annotations

from pathlib import Path
from pprint import pp

from cyclopts import App

from cwe_tools.paradox.files import expand_paths
from cwe_tools.paradox.script import parse_script
from cwe_tools.paradox.script.convert import to_python

app = App(
    name="parse",
    help="Parse Paradox script files and print their contents.",
)


@app.default
def parse_files(
    paths: list[Path],
    *,
    ast: bool = False,
) -> None:
    """Parse files and print either Python values or the raw AST."""
    files = expand_paths(paths)

    for index, path in enumerate(files):
        if index:
            print()

        if len(files) > 1:
            print(f"=== {path} ===")

        script = parse_script(path.read_text(encoding="utf-8-sig"))

        pp(
            script if ast else to_python(script),
            width=120,
            sort_dicts=False,
        )
