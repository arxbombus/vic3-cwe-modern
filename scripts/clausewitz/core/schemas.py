"""Predefined document schemas for Clausewitz-style data."""

from clausewitz.core.schema import DocumentSchema, KeyRule


def generic_schema(*, root_key: str = "root") -> DocumentSchema:
    root = KeyRule(name=root_key, repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=True))
    return DocumentSchema(name=f"generic:{root_key}", root_key=root_key, root_rule=root)


def technologies_schema() -> DocumentSchema:
    root = KeyRule(name="technologies", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=False))
    return DocumentSchema(name="technologies", root_key="technologies", root_rule=root)

__all__ = ["generic_schema", "technologies_schema"]
