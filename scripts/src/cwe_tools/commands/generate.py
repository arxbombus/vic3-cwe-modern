from __future__ import annotations

from pathlib import Path

from cyclopts import App

from cwe_tools.config import load_app_config
from cwe_tools.context import get_context
from cwe_tools.generators.map_data_state_regions import (
    build_plan,
    check_plan,
    write_plan,
)

app = App(name="generate", help="Generate deterministic CWE Modern content.")


@app.command
def map_data_state_regions(
    *,
    write: bool = False,
    check: bool = False,
    config: Path | None = None,
    manifest: Path | None = None,
    base_source: str | None = None,
    overlay_source: str | None = None,
    entity_path: str | None = None,
) -> None:
    """Generate complete map_data/state_regions replacement files."""
    if write == check:
        raise SystemExit("Specify exactly one of --write or --check")

    context = get_context()
    app_config = load_app_config(context, config)
    generator_config = app_config.generator("map_data_state_regions")
    manifest_path = manifest
    if manifest_path is None:
        raw = generator_config.manifest or "manifests/map_data_state_regions.toml"
        manifest_path = context.scripts / raw
    manifest_path = manifest_path.resolve()

    plan = build_plan(
        config=app_config,
        scripts_root=context.scripts,
        manifest_path=manifest_path,
        base_source_spec=base_source,
        overlay_source_spec=overlay_source,
        entity_path=entity_path,
    )

    if write:
        write_plan(plan, mod_root=app_config.mod_root, manifest_path=manifest_path)
        print(f"wrote {len(plan.outputs)} generated files")
        return

    problems = check_plan(plan, mod_root=app_config.mod_root)
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"ok: {len(plan.outputs)} generated files are current")
