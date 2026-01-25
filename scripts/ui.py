from __future__ import annotations

from pathlib import Path
from typing import Any

import questionary
from questionary import Style, path as questionary_path
import typer

from plan_api import ParamSpec

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


def number(message: str, *, default: float | int | None = None, integer: bool = False) -> float | int:
    default_text = None if default is None else str(default)
    ans = questionary.text(
        message,
        default=default_text,
        style=QUESTIONARY_STYLE,
    ).ask()
    if ans is None:
        raise typer.Abort()
    if integer:
        try:
            return int(ans)
        except ValueError as exc:
            raise typer.BadParameter(f"Expected an integer for {message}") from exc
    try:
        return float(ans)
    except ValueError as exc:
        raise typer.BadParameter(f"Expected a number for {message}") from exc


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


def _default_value(param: ParamSpec) -> Any:
    if param.default is not None:
        return param.default
    if param.kind == "select" and param.choices:
        return param.choices[0]
    if param.kind == "multiselect":
        return []
    if param.kind == "bool":
        return False
    return None


def resolve_defaults(
    params: list[ParamSpec], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    overrides = overrides or {}
    for param in params:
        if param.visible_if is not None and not param.visible_if(values):
            continue
        if param.name in overrides:
            value = overrides[param.name]
        else:
            value = _default_value(param)
        if param.kind == "multiselect" and isinstance(value, list):
            value = set(value)
        if param.validate is not None:
            value = param.validate(value)
        values[param.name] = value
    return values


def prompt_form(
    params: list[ParamSpec], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    overrides = overrides or {}
    for param in params:
        if param.visible_if is not None and not param.visible_if(values):
            continue
        if param.name in overrides:
            value = overrides[param.name]
            if param.kind == "multiselect" and isinstance(value, list):
                value = set(value)
        else:
            if param.kind == "bool":
                default = bool(param.default) if param.default is not None else False
                value = confirm(param.help or param.name, default=default)
            elif param.kind == "int":
                value = number(
                    param.help or param.name, default=param.default, integer=True
                )
            elif param.kind == "float":
                value = number(
                    param.help or param.name, default=param.default, integer=False
                )
            elif param.kind == "select":
                choices = param.choices or []
                value = select(
                    param.help or param.name,
                    choices=choices,
                    default=param.default,
                )
            elif param.kind == "multiselect":
                choices = param.choices or []
                value = multiselect(
                    param.help or param.name,
                    choices=choices,
                    default=param.default,
                )
            elif param.kind == "path":
                value = path(param.help or param.name, default=param.default)
            elif param.kind == "string":
                value = text(param.help or param.name, default=param.default)
            else:
                raise typer.BadParameter(f"Unknown param kind: {param.kind}")
        if param.validate is not None:
            value = param.validate(value)
        values[param.name] = value
    return values
