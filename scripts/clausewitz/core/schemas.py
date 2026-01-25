"""Predefined document schemas for HOI4 data."""

from clausewitz.core.schema import DocumentSchema, KeyRule


def technologies_schema() -> DocumentSchema:
    root = KeyRule(name="technologies", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=False))
    return DocumentSchema(name="technologies", root_key="technologies", root_rule=root)


__all__ = ["technologies_schema"]
