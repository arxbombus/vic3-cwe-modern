from __future__ import annotations

from pathlib import Path

from cyclopts import App

from cwe_tools.config import load_app_config
from cwe_tools.context import get_context
from cwe_tools.generators.map_data_state_regions import build_plan

app = App(name="validate", help="Run domain-level validation without writing files.")


@app.default
def validate(*, config: Path | None = None) -> None:
    context = get_context()
    app_config = load_app_config(context, config)
    generator = app_config.generator("map_data_state_regions")
    manifest_path = context.scripts / (
        generator.manifest or "manifests/map_data_state_regions.toml"
    )
    plan = build_plan(
        config=app_config,
        scripts_root=context.scripts,
        manifest_path=manifest_path,
    )
    if plan.validation_errors:
        raise SystemExit("\n".join(plan.validation_errors))
    print("ok: map_data_state_regions")
