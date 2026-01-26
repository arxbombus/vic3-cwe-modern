from __future__ import annotations

from enum import Enum

from clausewitz.core.schema import DocumentSchema
from clausewitz.core.schemas import generic_schema, technologies_schema


class SchemaChoice(str, Enum):
    generic = "generic"
    technologies = "technologies"


def resolve_schema(choice: SchemaChoice, *, root_key: str) -> DocumentSchema:
    if choice == SchemaChoice.technologies:
        return technologies_schema()
    if choice == SchemaChoice.generic:
        return generic_schema(root_key=root_key)
    raise ValueError(f"Unknown schema choice: {choice}")
