# Private workflow storage

Use during requested machine preparation or storage repair. Routine tasks do not load this procedure. Existing enrolled Projects retain their configured storage.

Inspect without changing configuration:

```sh
python3 -B <plugin-root>/scripts/workflow.py storage status
```

Verification stops after reporting this result. Missing storage is a setup prerequisite, not permission to initialize it.

For authorized preparation, reuse the selected canonical private directory. If none exists, include a proposed location, such as `~/.local/share/vibe-coding-workflow`, in the preparation scope. Keep it outside Git, targets, plugin caches and client instruction-discovery paths. Vendor plugin data and temporary plan directories do not select shared storage.

Run `storage prepare` with bounded JSON on standard input:

```sh
python3 -B <plugin-root>/scripts/workflow.py storage prepare
```

```json
{"private_data_dir":"/absolute/private/path"}
```

The machine configuration at `~/.config/vibe-coding-workflow/machine.json` preserves the selected location and original authority bindings. Identical preparation reuses it. Another selection, interrupted initialization, missing or replaced storage, and uncertain ownership remain protected. Preserve configuration and partial files; do not delete, recreate, repin or choose another store to clear the condition. Report the observed blocker for reconciliation. This slice does not automate interrupted setup repair.

The helper creates private schema-3 review evidence without enrolling a target or fabricating Project/task records. An explicitly requested unenrolled review can resolve an ordinary Repository owner with `storage owner --cwd PATH`; repeated subsets and benign aliases reuse original identity and age. Enrolled, overlapping and unsupported worktree cases remain protected until their accounting acquisition is implemented.

Completion means the selected authority reopens with its original bindings and produces a stable owner through the supported control. Package checks do not prove client execution, complete temporary retention, Project caps or detailed-report admission. Continue using bounded chat findings while those lifecycle requirements remain unavailable.
