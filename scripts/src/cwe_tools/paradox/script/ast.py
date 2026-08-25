from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scalar:
    text: str
    quoted: bool = False


@dataclass
class Block:
    entries: list[Entry] = field(default_factory=list)


@dataclass
class TaggedBlock:
    tag: str
    block: Block


Value = Scalar | Block | TaggedBlock


@dataclass
class Assignment:
    key: str
    value: Value
    operator: str = "="


@dataclass
class ValueEntry:
    value: Value


@dataclass
class Comment:
    text: str


@dataclass
class Commented:
    """An entry intentionally rendered as line comments."""

    entry: Entry


Entry = Assignment | ValueEntry | Comment | Commented


@dataclass
class Script:
    entries: list[Entry] = field(default_factory=list)
