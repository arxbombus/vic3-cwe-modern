# Task Completion

No universal automated suite exists. Use the smallest applicable checks plus game validation:

1. Always inspect scope with `git status --short` and `git diff -- <changed paths>`; do not include unrelated pre-existing changes.
2. Always run `git diff --check`.
3. For Python changes, run each affected CLI with `--help`, then exercise the changed path against temporary or explicit non-production output. Run `uv run --project scripts python <script> ...` from the root.
4. For `modify_state_resources.py`, validate behavior with `--dry-run` before any output-producing invocation.
5. For Era 11-20 generator/manifests/generated definitions, regenerate to a separate output directory and require `validation/validation.json` to contain zero errors; review warnings, generated manifest, and output diff. The generator writes its own structural validation report but is not a full game parser.
6. For localization, preserve UTF-8 BOM, confirm the `l_<language>:` header and indentation, and check that new/renamed gameplay keys have matching localization.
7. For gameplay, history, map, event, GUI, or asset changes, launch Victoria 3 with only CWE enabled, inspect the game error log for new parser/runtime errors, and exercise the affected start date/UI/event/mechanic. In-game validation is required because no repository-wide Clausewitz/Jomini validator is configured.
8. If metadata or replaced paths change, verify launcher recognition and confirm the effective replaced directory still contains every definition the mod intends to retain.
