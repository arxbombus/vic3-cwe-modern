"""Schema definitions for Clausewitz documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ClausewitzValueKind = Literal["scalar", "block", "list", "comparison", "any"]


@dataclass(slots=True)
class KeyRule:
    """Schema rule describing how a particular key behaves."""

    name: str
    kind: ClausewitzValueKind = "any"
    repeatable: bool = False
    children: dict[str, KeyRule] = field(default_factory=dict[str, "KeyRule"])
    wildcard: KeyRule | None = None

    def child(self, key: str) -> KeyRule | None:
        return self.children.get(key) or self.wildcard

    def register_child(self, rule: KeyRule) -> None:
        if rule.name == "*":
            self.wildcard = rule
        else:
            self.children[rule.name] = rule


@dataclass(slots=True)
class DocumentSchema:
    """Schema describing a Clausewitz document type (e.g., technologies)."""

    name: str
    root_key: str
    root_rule: KeyRule

    def rule_for_path(self, path: list[str]) -> KeyRule | None:
        if not path or path[0] != self.root_key:
            return None
        rule = self.root_rule
        for key in path[1:]:
            rule = rule.child(key)
            if rule is None:
                return None
        return rule
