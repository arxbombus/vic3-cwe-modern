from cwe_tools.paradox.script import format_script, parse_script
from cwe_tools.paradox.script.ast import Assignment, Block
from cwe_tools.paradox.script.edit import find_assignments


def test_repeated_assignments_and_tagged_blocks_round_trip() -> None:
    source = """
foo = {
    color = rgb{ 110 172 154 }
    resource = { type = "building_oil_rig" undiscovered_amount = 5 }
    resource = { type = "building_rubber_plantation" undiscovered_amount = 10 }
}
"""
    document = parse_script(source)
    foo = document.entries[0]
    assert isinstance(foo, Assignment)
    assert isinstance(foo.value, Block)
    assert len(find_assignments(foo.value, "resource")) == 2

    formatted = format_script(document)
    parse_script(formatted)
    assert "rgb{ 110 172 154 }" in formatted


def test_anonymous_blocks_for_map_locators() -> None:
    source = """
game_object_locator = {
    name = "city"
    instances = {
        { id = 1500 position = { 1 0 2 } rotation = { 0 -1 0 0 } }
    }
}
"""
    formatted = format_script(parse_script(source))
    assert "id = 1500" in formatted
    parse_script(formatted)
