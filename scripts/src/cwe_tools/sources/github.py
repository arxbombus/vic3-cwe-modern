from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GitHubSource:
    repo: str
    ref: str = "master"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "cwe-modern-tools",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get(self, url: str) -> bytes:
        request = Request(url, headers=self._headers())
        with urlopen(request, timeout=30) as response:
            return response.read()

    def read_text(self, path: str | PurePosixPath) -> str:
        relative = PurePosixPath(str(path)).as_posix().lstrip("/")
        owner, repo = self.repo.split("/", 1)
        url = (
            f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
            f"{quote(self.ref, safe='')}/{quote(relative, safe='/')}"
        )
        return self._get(url).decode("utf-8-sig")

    def list_files(
        self,
        directory: str | PurePosixPath,
        *,
        suffix: str | None = None,
    ) -> list[str]:
        relative = PurePosixPath(str(directory)).as_posix().strip("/")
        url = (
            f"https://api.github.com/repos/{self.repo}/contents/"
            f"{quote(relative, safe='/')}?ref={quote(self.ref, safe='')}"
        )
        payload = json.loads(self._get(url))
        if not isinstance(payload, list):
            raise RuntimeError(f"GitHub path is not a directory: {relative}")
        result: list[str] = []
        for item in payload:
            if item.get("type") != "file":
                continue
            path = str(item["path"])
            if suffix is not None and not path.endswith(suffix):
                continue
            result.append(path)
        return sorted(result)
