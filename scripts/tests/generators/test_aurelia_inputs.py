from pathlib import Path

from cwe_tools.paradox.localization import parse_localization
from cwe_tools.victoria3.state_regions import parse_state_region_file

ROOT = Path(__file__).resolve().parents[2]


def test_supplied_aurelia_state_file_parses() -> None:
    path = ROOT / "data" / "aurelia" / "00_modern_states.txt"
    states = parse_state_region_file(
        "map_data/state_regions/00_modern_states.txt",
        path.read_text(encoding="utf-8-sig"),
    )
    names = {state.name for state in states}
    assert "STATE_FORMOSA" in names
    assert "STATE_EAST_FORMOSA" in names
    assert "STATE_GREATER_RIAU_ISLANDS" in names


def test_supplied_aurelia_localization_parses() -> None:
    path = ROOT / "data" / "aurelia" / "0_modern_states_l_english.yml"
    document = parse_localization(path.read_text(encoding="utf-8-sig"))
    assert document.language == "l_english"
