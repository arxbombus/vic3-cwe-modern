from __future__ import annotations

from pathlib import Path

import questionary
from questionary import Style, path as questionary_path
import typer

QUESTIONARY_STYLE = Style(
    [
        ("qmark", "fg:#00afff bold"),
        ("question", "bold"),
        ("answer", "fg:#00ff87 bold"),
        ("pointer", "fg:#00afff bold"),
        ("highlighted", "fg:#00afff bold"),
        ("selected", "fg:#00ff87"),
        ("separator", "fg:#888888"),
        ("instruction", "fg:#888888"),
        ("text", ""),
        ("disabled", "fg:#666666 italic"),
    ]
)


def select(message: str, *, choices: list[str], default: str | None = None) -> str:
    ans = questionary.select(
        message,
        choices=choices,
        default=default,
        show_selected=True,
        use_indicator=True,
        pointer=">",
        use_arrow_keys=True,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    return ans


def multiselect(
    message: str, *, choices: list[str], default: list[str] | None = None
) -> set[str]:
    ans = questionary.checkbox(
        message,
        choices=choices,
        default=default,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    return set(ans)


def confirm(message: str, *, default: bool = True) -> bool:
    ans = questionary.confirm(
        message,
        default=default,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    return bool(ans)


def text(message: str, *, default: str | None = None) -> str:
    ans = questionary.text(
        message,
        default=default,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    return ans


def path(message: str, *, default: Path | None = None) -> Path:
    default_text = None if default is None else str(default)
    ans = questionary_path(
        message,
        default=default_text,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    return Path(ans)
