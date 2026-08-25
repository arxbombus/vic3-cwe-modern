from cwe_tools.paradox.localization import format_localization, parse_localization


def test_localization_round_trip() -> None:
    source = """\ufeffl_english:
  # comment
  STATE_TEST: "Test State"
  STATE_OTHER:0 "Other"
"""
    parsed = parse_localization(source)
    assert parsed.language == "l_english"
    formatted = format_localization(parsed)
    assert 'STATE_TEST: "Test State"' in formatted
    assert 'STATE_OTHER:0 "Other"' in formatted
