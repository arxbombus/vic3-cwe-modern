# Project Core

- Cold War Era (CWE) modern-era Victoria 3 mod; upstream repository is `arxbombus/vic3-cwe-modern`. Root README describes this branch as the less-stable development version.
- Mod identity/version contract lives in `.metadata/metadata.json`: id `com.arxbombus.cwe-modern`, supported Victoria 3 `1.13.*`, multiplayer-synchronized.
- Source map:
  - `common/`: gameplay definitions and history; dominant source area.
  - `events/`: historical and system event scripts.
  - `localization/<language>/`: Paradox localization YAML.
  - `map_data/`: state regions and map definitions.
  - `gui/`, `gfx/`, `fonts/`, `music/`: UI and assets.
  - `scripts/`: Python maintenance/generation utilities plus Era 11-20 manifests and validation artifacts.
- Many `common/`, `events/`, `music/`, and `gfx/` paths are declared in `game_custom_data.replace_paths`. Treat these as whole-path overrides: missing vanilla definitions under a replaced path may be intentionally removed, and edits must consider the complete effective dataset rather than additive mod semantics.
- Preserve existing user changes; this working project commonly contains active uncommitted mod work.
- Toolchain details: `mem:tech_stack`.
- Runnable developer commands: `mem:suggested_commands`.
- Project-specific file conventions: `mem:conventions`.
- Definition of done and validation limits: `mem:task_completion`.
