from pathlib import Path


def read_text(path: Path) -> str:
    """Read a text file while tolerating UTF-8 BOMs."""
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def content_changed(path: Path, expected: str) -> bool:
    """Return whether a file differs from the expected generated content."""
    if not path.exists():
        return True

    return read_text(path) != expected
