from pathlib import Path

from cyclopts import App

app = App(
    name="transform",
    help="Transform Victoria 3 data files.",
)


@app.command
def resources(
    source: Path,
    *,
    output: Path | None = None,
) -> None:
    """Transform state resource definitions."""
    print(f"Source: {source}")
    print(f"Output: {output}")
    print("Resource transformer not yet migrated.")


@app.command
def buy_packages(
    source: Path,
    *,
    output: Path | None = None,
) -> None:
    """Transform buy package definitions."""
    print(f"Source: {source}")
    print(f"Output: {output}")
    print("Buy-package transformer not yet migrated.")
