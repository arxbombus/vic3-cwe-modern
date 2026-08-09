# /// script
# dependencies = [
#     "wand>=0.7.2",
# ]
# ///

from argparse import ArgumentParser
from pathlib import Path

from wand.image import Image


def convert_png(path: Path, delete_source: bool = False) -> None:
    output = path.with_suffix(".dds")

    with Image(filename=str(path)) as image:
        image.options["dds:compression"] = "dxt5"
        image.options["dds:mipmaps"] = "0"

        image.format = "dds"
        image.save(filename=str(output))

    print(f"✓ {path} -> {output}")

    if delete_source:
        path.unlink()
        print(f"  Deleted: {path}")


def main() -> None:
    parser = ArgumentParser(
        description="Convert PNG files to DDS for Victoria 3 modding."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="PNG files or directories containing PNG files.",
    )
    parser.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="Delete source PNG files after successful conversion.",
    )

    args = parser.parse_args()

    files: set[Path] = set()

    for path in args.paths:
        if path.is_dir():
            files.update(
                p for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() == ".png"
            )
        elif path.is_file() and path.suffix.lower() == ".png":
            files.add(path)
        else:
            print(f"Skipping: {path}")

    if not files:
        print("No PNG files found.")
        return

    converted = 0

    for path in sorted(files):
        try:
            convert_png(path, delete_source=args.delete)
            converted += 1
        except Exception as exc:
            print(f"✗ Failed: {path}")
            print(f"  {exc}")

    print(f"\nConverted {converted}/{len(files)} file(s).")


if __name__ == "__main__":
    main()