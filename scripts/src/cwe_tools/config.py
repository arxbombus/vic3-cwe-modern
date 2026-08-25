from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cwe_tools.context import RepoContext


@dataclass(frozen=True)
class SourceConfig:
    type: str
    path: str | None = None
    repo: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class EntityConfig:
    path: str
    base_source: str | None = None
    overlay_source: str | None = None


@dataclass(frozen=True)
class GeneratorConfig:
    entity: str | None = None
    manifest: str | None = None
    base_source: str | None = None
    overlay_source: str | None = None


@dataclass(frozen=True)
class AppConfig:
    mod_root: Path
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    entities: dict[str, EntityConfig] = field(default_factory=dict)
    generators: dict[str, GeneratorConfig] = field(default_factory=dict)

    def entity(self, name: str) -> EntityConfig:
        try:
            return self.entities[name]
        except KeyError as exc:
            raise KeyError(f"Unknown entity {name!r}") from exc

    def generator(self, name: str) -> GeneratorConfig:
        try:
            return self.generators[name]
        except KeyError as exc:
            raise KeyError(f"Unknown generator {name!r}") from exc


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_app_config(context: RepoContext, path: Path | None = None) -> AppConfig:
    config_path = (path or context.app_config).resolve()
    data = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    base_dir = config_path.parent

    app = _mapping(data.get("app"))
    raw_mod_root = str(app.get("mod_root", ".."))
    mod_root = (base_dir / raw_mod_root).resolve()

    sources = {
        name: SourceConfig(
            type=str(raw["type"]),
            path=str(raw["path"]) if "path" in raw else None,
            repo=str(raw["repo"]) if "repo" in raw else None,
            ref=str(raw.get("ref", "master")) if raw.get("repo") else None,
        )
        for name, raw in _mapping(data.get("sources")).items()
    }

    entities = {
        name: EntityConfig(
            path=str(raw["path"]),
            base_source=str(raw["base_source"]) if "base_source" in raw else None,
            overlay_source=str(raw["overlay_source"])
            if "overlay_source" in raw
            else None,
        )
        for name, raw in _mapping(data.get("entities")).items()
    }

    generators = {
        name: GeneratorConfig(
            entity=str(raw["entity"]) if "entity" in raw else None,
            manifest=str(raw["manifest"]) if "manifest" in raw else None,
            base_source=str(raw["base_source"]) if "base_source" in raw else None,
            overlay_source=str(raw["overlay_source"])
            if "overlay_source" in raw
            else None,
        )
        for name, raw in _mapping(data.get("generators")).items()
    }

    # Resolve local source paths relative to app.toml, not the current shell.
    resolved_sources: dict[str, SourceConfig] = {}
    for name, source in sources.items():
        if source.type == "local" and source.path is not None:
            local = Path(source.path)
            if not local.is_absolute():
                local = (base_dir / local).resolve()
            resolved_sources[name] = SourceConfig(type="local", path=str(local))
        else:
            resolved_sources[name] = source

    return AppConfig(
        mod_root=mod_root,
        sources=resolved_sources,
        entities=entities,
        generators=generators,
    )
