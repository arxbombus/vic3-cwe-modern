from pathlib import Path

from cwe_tools.config import AppConfig, EntityConfig, GeneratorConfig, SourceConfig
from cwe_tools.generators.map_data_state_regions import build_plan

BASE_FILE = """
STATE_A = {
    id = 1
    provinces = { "xAAAAAA" }
    arable_land = 10
    capped_resources = { building_coal_mine = 5 }
}
STATE_B = {
    id = 2
    provinces = { "xBBBBBB" }
    arable_land = 20
    capped_resources = { building_coal_mine = 5 }
}
"""

OVERLAY_FILE = """
STATE_A = {
    id = 1
    provinces = { "xAAAAAA" }
    arable_land = 10
    capped_resources = { building_coal_mine = 7 }
}
"""


def test_base_then_overlay_then_manifest_generation(tmp_path: Path) -> None:
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    mod = tmp_path / "mod"
    scripts = mod / "scripts"
    manifest = scripts / "manifests" / "map_data_state_regions.toml"

    (base / "map_data/state_regions").mkdir(parents=True)
    (overlay / "map_data/state_regions").mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    (base / "map_data/state_regions/00_test.txt").write_text(BASE_FILE)
    (overlay / "map_data/state_regions/cwe_replacement_states.txt").write_text(
        OVERLAY_FILE
    )
    # Represents a stale output from the developer fork; bootstrap exclusion
    # must keep it out of the input dataset.
    (overlay / "map_data/state_regions/00_test_replace.txt").write_text("BROKEN = { }")

    manifest.write_text(
        """
[source]
base_source = "base"
overlay_source = "overlay"
path = "map_data/state_regions"
bootstrap_exclude_globs = ["*_replace.txt"]
include_files = ["cwe_replacement_states.txt"]

[output]
directory = "map_data/state_regions"
ownership_file = "scripts/.generated/map_data_state_regions.json"

[global]
arable_land_multiplier = 2.0

[global.capped_resource_multipliers]
building_coal_mine = 2.0

[aurelia]
enabled = false
"""
    )

    config = AppConfig(
        mod_root=mod,
        sources={
            "base": SourceConfig(type="local", path=str(base)),
            "overlay": SourceConfig(type="local", path=str(overlay)),
        },
        entities={
            "map_data_state_regions": EntityConfig(
                path="map_data/state_regions",
                base_source="base",
                overlay_source="overlay",
            )
        },
        generators={
            "map_data_state_regions": GeneratorConfig(
                entity="map_data_state_regions",
                manifest="manifests/map_data_state_regions.toml",
            )
        },
    )

    plan = build_plan(
        config=config,
        scripts_root=scripts,
        manifest_path=manifest,
    )
    assert not plan.validation_errors
    rendered = plan.outputs["map_data/state_regions/00_test_replace.txt"]
    assert "building_coal_mine = 14" in rendered
    assert "building_coal_mine = 10" in rendered
    assert "arable_land = 20" in rendered
    assert "arable_land = 40" in rendered
