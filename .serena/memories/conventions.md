# Conventions

- Paradox definitions use stable snake_case IDs; references are namespace-like tokens such as `c:TAG`, scripted scopes, triggers, and effects. Preserve identifier compatibility unless all references and localization are updated.
- Gameplay script style is brace-delimited, tab-indented in established files, with comments using `#` or prominent `###` section labels. Match the surrounding file rather than reformatting unrelated content.
- Many history and definition files rely on load order and filename prefixes (`00_`, `01_`, `z_`); renames can change override order and behavior.
- Respect `.metadata/metadata.json` replacement semantics. A file in a replaced directory participates in a complete mod-owned dataset, not merely a vanilla patch.
- Localization files begin with `l_<language>:`; keys are indented two spaces and commonly include the `:0` version marker. Preserve UTF-8 BOM when editing.
- Python utilities use `pathlib.Path`, type annotations, argparse CLIs, dataclasses where useful, and `if __name__ == "__main__":` entrypoints. Preserve source encoding/line endings where tools explicitly promise to do so.
- Generated Era 11-20 content is governed by `scripts/manifests/` and `scripts/tools/generate_era11_20.py`; do not hand-edit generated outputs without determining whether the generator/manifests must change as the source of truth.
- Large binary assets are part of the mod. Avoid incidental conversions or recompression.
