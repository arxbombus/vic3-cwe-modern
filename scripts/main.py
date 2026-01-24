from __future__ import annotations

from pathlib import Path

import typer

from clausewitz import ClausewitzFormatter, ClausewitzParser, DocumentSchema, KeyRule
from clausewitz.nodes import ClausewitzScalarValue
from clausewitz.nodes import ClausewitzBlock


def generic_schema() -> DocumentSchema:
    root = KeyRule(name="root", repeatable=False)
    root.register_child(KeyRule(name="*", repeatable=True))
    return DocumentSchema(name="generic", root_key="root", root_rule=root)


def _scale_targets(block: ClausewitzBlock, factor: float) -> int:
    count = 0
    for entry in block.entries:
        if entry.key == "building_modifiers" and isinstance(
            entry.value, ClausewitzBlock
        ):
            for sub in entry.value.entries:
                if sub.key == "level_scaled" and isinstance(sub.value, ClausewitzBlock):
                    for leaf in sub.value.entries:
                        if leaf.key.startswith(
                            "building_employment_"
                        ) and leaf.key.endswith("_add"):
                            if isinstance(
                                leaf.value, ClausewitzScalarValue
                            ) and isinstance(leaf.value.value, (int, float)):
                                leaf.value.value = leaf.value.value / factor
                                leaf.value.raw = str(leaf.value.value)
                                count += 1
    return count


def _format_document(document, *, preserve: bool = True) -> str:
    formatter = ClausewitzFormatter(mode="preserve" if preserve else "format")
    return formatter.format_document(document)


def apply(
    directory: Path = Path("../common/production_methods"),
    factor: float = 2.0,
    dry_run: bool = False,
) -> None:
    schema = generic_schema()
    for path in sorted(directory.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        document = ClausewitzParser(text, schema).parse_document()
        changes = _scale_targets(document.root, factor)
        if changes == 0:
            continue
        if dry_run:
            typer.echo(f"{path}: would update {changes} values")
            continue
        path.write_text(_format_document(document), encoding="utf-8")
        typer.echo(f"{path}: updated {changes} values")


def main():
    apply()


if __name__ == "__main__":
    main()
