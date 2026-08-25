from decimal import Decimal

from cwe_tools.paradox.script.formatter import format_script
from cwe_tools.victoria3.state_regions import (
    add_discoverable_resource,
    multiply_capped_resource,
    parse_state_region_file,
    state_script,
)


def test_state_resource_editing_preserves_repeated_resource_blocks() -> None:
    source = """
STATE_TEST = {
    id = 1
    provinces = { "xAAAAAA" }
    arable_land = 10
    capped_resources = { building_coal_mine = 5 }
    resource = { type = "building_oil_rig" undiscovered_amount = 2 }
}
"""
    state = parse_state_region_file("map_data/state_regions/00_test.txt", source)[0]
    assert multiply_capped_resource(state, "building_coal_mine", Decimal("2"))
    add_discoverable_resource(
        state,
        building="building_rubber_plantation",
        undiscovered_amount=7,
    )
    rendered = format_script(state_script([state]))
    assert "building_coal_mine = 10" in rendered
    assert rendered.count("resource = {") == 2
