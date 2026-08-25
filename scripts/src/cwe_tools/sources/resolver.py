from __future__ import annotations

from pathlib import Path

from cwe_tools.config import AppConfig, SourceConfig
from cwe_tools.sources.github import GitHubSource
from cwe_tools.sources.local import LocalSource
from cwe_tools.sources.models import FileSource


class SourceResolver:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def resolve(self, spec: str) -> FileSource:
        """Resolve a named source or inline local:/github: source specification."""
        if spec in self.config.sources:
            return self._from_config(self.config.sources[spec])

        if spec.startswith("local:"):
            return LocalSource(Path(spec.removeprefix("local:")).expanduser().resolve())

        if spec.startswith("github:"):
            payload = spec.removeprefix("github:")
            if "@" in payload:
                repo, ref = payload.rsplit("@", 1)
            else:
                repo, ref = payload, "master"
            if repo.count("/") != 1:
                raise ValueError("GitHub source must be github:OWNER/REPO[@REF]")
            return GitHubSource(repo=repo, ref=ref)

        # Convenient CLI fallback: an unregistered value is treated as a path.
        return LocalSource(Path(spec).expanduser().resolve())

    @staticmethod
    def _from_config(source: SourceConfig) -> FileSource:
        if source.type == "local":
            if source.path is None:
                raise ValueError("Local source requires path")
            return LocalSource(Path(source.path))
        if source.type == "github":
            if source.repo is None:
                raise ValueError("GitHub source requires repo")
            return GitHubSource(repo=source.repo, ref=source.ref or "master")
        raise ValueError(f"Unsupported source type: {source.type}")
