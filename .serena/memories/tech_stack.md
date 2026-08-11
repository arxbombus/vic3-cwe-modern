# Tech Stack

- Primary language: Paradox Clausewitz/Jomini script in `.txt` plus Victoria 3 GUI script in `.gui`; VS Code maps both to language id `vic3` and disables format-on-save.
- Localization: Paradox YAML (`.yml`) organized by language; files use UTF-8 with BOM.
- Assets: DDS/PNG textures and icons, mesh/asset descriptors, MP3 music, TTF fonts.
- Auxiliary tooling: Python `>=3.13`, pinned by `scripts/.python-version` and managed with `uv` via `scripts/pyproject.toml` + `scripts/uv.lock`.
- Only declared Python dependency is Wand `0.7.2+` for PNG-to-DDS conversion; Wand requires a usable ImageMagick installation at runtime.
- `scripts/tools/generate_era11_20.py` contains a lightweight Clausewitz/Jomini parser plus the manifest-driven Era 11-20 generator and its structural validator.
- No repository-wide formatter, linter, type checker, or test framework is configured.
