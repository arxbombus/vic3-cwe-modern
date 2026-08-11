# Suggested Commands (PowerShell, from project root)

## Environment

- Sync Python tooling: `cd scripts; uv sync; cd ..`
- Run without activating the venv: `uv run --project scripts python <script> ...`
- Existing local interpreter fallback: `.\scripts\.venv\Scripts\python.exe <script> ...`

## Safe inspection

- Working tree: `git status --short --branch`
- Find tracked/project files: `rg --files`
- Search source: `rg -n "PATTERN" common events localization map_data gui scripts`
- Whitespace/conflict-marker validation: `git diff --check`

## Maintenance tools

- State-resource dry run: `uv run --project scripts python scripts/modify_state_resources.py <input> --resource iron=2 --dry-run`
- State-resource generation: use the same command with explicit `-o <output>` and omit `--dry-run`.
- Buy-package generation: `uv run --project scripts python scripts/scale_buy_packages_v2.py scripts/base_buy_packages.txt -o common/buy_packages/00_buy_packages.txt <scaling options>`
- PNG conversion: `uv run --project scripts python scripts/png_to_dds.py <png-or-directory>`; `--delete` is destructive and should only be used deliberately.
- Era 11-20 generator (from `scripts/`): `uv run python tools/generate_era11_20.py --source <current-CWE-root> --output <output-root> --manifests manifests`. Always use an explicit output root unless intentional in-place regeneration is desired.

## Game run

- Enable only CWE Modern in a Victoria 3 launcher playlist and launch the game. This repository is already located under the standard Windows Victoria 3 `Documents\Paradox Interactive\Victoria 3\mod` directory.
