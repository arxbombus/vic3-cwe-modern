from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from .. import ui
from .spec import ParamKind, ParamSpec


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
        if param.kind == ParamKind.multiselect and isinstance(value, list):
            value = set(value)
        if param.validate is not None:
            value = param.validate(value)
        values[param.name] = value
    return values


def prompt_params(
    params: list[ParamSpec], overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    overrides = overrides or {}
    for param in params:
        if param.visible_if is not None and not param.visible_if(values):
            continue
        if param.name in overrides:
            value = overrides[param.name]
            if param.kind == ParamKind.multiselect and isinstance(value, list):
                value = set(value)
        else:
            value = _prompt_value(param)
        if param.validate is not None:
            value = param.validate(value)
        values[param.name] = value
    return values


def coerce_overrides(params: list[ParamSpec], overrides: dict[str, str]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    param_map = {param.name: param for param in params}
    for key, raw in overrides.items():
        param = param_map.get(key)
        if param is None:
            raise typer.BadParameter(f"Unknown plan parameter: {key}")
        if param.kind == ParamKind.bool:
            coerced[key] = _parse_bool(raw)
        elif param.kind == ParamKind.int:
            coerced[key] = _parse_int(raw, key)
        elif param.kind == ParamKind.float:
            coerced[key] = _parse_float(raw, key)
        elif param.kind == ParamKind.multiselect:
            coerced[key] = [item.strip() for item in raw.split(",") if item.strip()]
        elif param.kind == ParamKind.path:
            coerced[key] = Path(raw)
        else:
            coerced[key] = raw
    return coerced


def _default_value(param: ParamSpec) -> Any:
    if param.default is not None:
        return param.default
    if param.kind == ParamKind.select and param.choices:
        return param.choices[0]
    if param.kind == ParamKind.multiselect:
        return []
    if param.kind == ParamKind.bool:
        return False
    return None


def _prompt_value(param: ParamSpec) -> Any:
    if param.kind == ParamKind.bool:
        default = bool(param.default) if param.default is not None else False
        return ui.confirm(param.help or param.name, default=default)
    if param.kind == ParamKind.int:
        return _prompt_number(param, integer=True)
    if param.kind == ParamKind.float:
        return _prompt_number(param, integer=False)
    if param.kind == ParamKind.select:
        choices = param.choices or []
        return ui.select(param.help or param.name, choices=choices, default=param.default)
    if param.kind == ParamKind.multiselect:
        choices = param.choices or []
        return ui.multiselect(param.help or param.name, choices=choices, default=param.default)
    if param.kind == ParamKind.path:
        return ui.path(param.help or param.name, default=param.default)
    if param.kind == ParamKind.string:
        return ui.text(param.help or param.name, default=param.default)
    raise typer.BadParameter(f"Unknown param kind: {param.kind}")


def _prompt_number(param: ParamSpec, *, integer: bool) -> float | int:
    message = param.help or param.name
    raw = ui.text(message, default=str(param.default) if param.default is not None else None)
    if integer:
        try:
            return int(raw)
        except ValueError as exc:
            raise typer.BadParameter(f"Expected an integer for {message}") from exc
    try:
        return float(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"Expected a number for {message}") from exc


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"true", "1", "yes", "y"}:
        return True
    if value in {"false", "0", "no", "n"}:
        return False
    raise typer.BadParameter(f"Expected a boolean, got '{raw}'")


def _parse_int(raw: str, key: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"Expected an integer for {key}") from exc


def _parse_float(raw: str, key: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"Expected a float for {key}") from exc
