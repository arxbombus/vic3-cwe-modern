from pathlib import Path

from cyclopts import App

app = App(
    name="assets",
    help="Process Victoria 3 assets.",
)


@app.command
def png_to_dds(
    paths: list[Path],
    *,
    delete: bool = False,
) -> None:
    """Convert PNG assets to DDS."""
    print(f"Paths: {paths}")
    print(f"Delete sources: {delete}")
    print("DDS converter not yet migrated.")
