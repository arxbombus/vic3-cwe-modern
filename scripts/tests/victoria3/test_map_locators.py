from cwe_tools.paradox.script import format_script, parse_script
from cwe_tools.victoria3.map_locators import Locator, set_locator


def test_set_locator_updates_existing_and_adds_new() -> None:
    source = """
game_object_locator = {
    name = "city"
    instances = {
        { id = 1500 position = { 1 0 2 } rotation = { 0 0 0 1 } scale = { 1 1 1 } }
    }
}
"""
    document = parse_script(source)
    set_locator(
        document,
        Locator(
            id=1500,
            position=(10.0, 0.0, 20.0),
            rotation=(0.0, -1.0, 0.0, 0.0),
        ),
    )
    set_locator(
        document,
        Locator(
            id=1501,
            position=(11.0, 0.0, 21.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
        ),
    )
    rendered = format_script(document)
    assert "id = 1500" in rendered
    assert "id = 1501" in rendered
    assert "position = { 10.0 0.0 20.0 }" in rendered
