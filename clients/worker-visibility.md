# Worker roles in Habblaud

Load this contract for an assignment using an already approved Habblaud
connection. Visibility is optional and separate from task titles, resource
admission, recovery and execution. Use the same declaration for ordinary and
managed native workers, reviewers, supervisors and OpenRouter workers.

## Declare before dispatch

Record this versioned object in the existing assignment context:

```json
{"version":1,"role":"Reviewer","specialty":"Security assessment","custom_role_name":"Threat reviewer"}
```

Choose the actual responsibility: `Coordinator`, `Scout`, `Builder`, `Tester`,
`Reviewer`, `Scribe` or `Investigator`. Never infer it from a task name, model,
specialty or D6 authority role. Supply `custom_role_name` only when explicitly
declared. Specialty and custom name are nonblank printable text, each at most
4,096 characters. Preserve Unicode and the exact custom name. A custom name
appears as `Custom role name · Model Display Name`; otherwise use
`Role · Model Display Name`. Retain canonical role and specialty separately.
The full label is sent in the existing display field without truncation. Report
an unsupported label or receiver capability explicitly; the transport enforces
its wire byte limit separately from the declared text lengths. Never substitute a
generic role. Legacy assignments without a declaration stay unknown.

## Native workers and reviewers

For managed D6 worker preparation or D5 review preparation, include the object
as optional `visibility`. Use the original declaration returned by preparation.
It is part of the immutable request and its digest, separate from authority
roles and review report digests. It grants no launch, review or reconciliation
permission. Ordinary native work uses the same metadata without an enrollment,
runtime task or database.

Before native dispatch, use the following helper in the existing private task
context. The context path is an unused absolute file in a canonical, owner-only
directory outside repositories and installed package trees. The helper rejects
the selected checkout, Git worktrees and the package roots it uses:

```text
python3 -I -B <package>/scripts/worker_visibility.py prepare --context <private-context-file>
```

Supply `parent_session_id` (actual native UUID), `checkout` (canonical absolute
working directory), `task_name` (the existing immutable creation name), and
`visibility` (the object above) on stdin. For managed workers also supply
`ledger_assignment_digest`: the prepared worker's `assignment_digest` or the
reviewer's distinct `ledger_assignment_digest`. Preserve the exact managed
prompt. For ordinary native work, place the returned `prompt_marker` on the
first line of the brief. This binds visibility when native history omits the
agent path. Preparation reserves display metadata only; preserve the native
tool's original `task_name` and attempt marker.

### Forward the original Desktop start event

When the existing Habblaud `SubagentStart` command is configured to use this
adapter, prepare with `--context-directory <private-directory>` instead of
`--context`. Use the exact directory configured in the hook and retain the
returned context path. Allocate a distinct task name for each new child.

Wrap the existing command with the reviewed package:

```text
python3 -I -B <package>/scripts/worker_visibility.py forward-start
  --context-directory <private-directory> --checkout <canonical-checkout>
  --codex-executable <absolute-reviewed-Codex-executable>
  -- <original-command-and-arguments>
```

Preserve the original hook configuration for recovery. Review the changed
command through Codex's supported hook trust flow and use a Desktop session
that has loaded it. Project hooks run alongside user hooks. Adding a second
hook does not replace the original Habblaud command.

The wrapper checks the genuine child, parent, checkout and creation name with
the native observer. It preserves a native role and forwards the original
event if the private declaration or live identity is unavailable. When the
declaration matches, it adds the label to the event copy and calls the existing
command. Habblaud 1.0.3 may capitalize or clip labels. This route forwards
labels that fit 200 UTF-16 units and survive that normalization. Qualify the
first visible badge using a fresh worker. Rollout discovery can still register
the child before the hook.

### Publish after dispatch

After successful dispatch, use the actual returned child UUID and a short
observed `phase` in `{"worker_id":"<actual-child-uuid>","phase":"Working"}`:

```text
python3 -I -B <package>/scripts/worker_visibility.py publish --context <same-file>
  --visibility-plugin <trusted-installed-local-model-delegation-root>
  --habblaud-endpoint <literal-loopback-HTTP-url>
  --habblaud-account <observed-Codex-account-id>
```

The Codex adapter checks actual parent/child lineage and checkout. The native
path must match the original creation name. If the path is absent, also provide
the actual `parent_turn_id` and `spawn_item_id` in the publish request. It reads
that exact spawn item and checks the original marker or immutable assignment
digest without forwarding any prompt. Same-parent lineage alone is insufficient.
The observed configured model supplies display text; this does not establish
the execution model. Missing observations produce no character. Do not publish
a proposed child, failed launch or fabricated native log.

Use the same context and child for continuation, recovery and meaningful phase
changes. Do not retire the display on an intermediate turn completion. Use a
terminal display phase only when retiring that assignment. An authorized new
attempt or native fallback with a real new child uses a new context with the
same declaration and its own observed identity. A direct coordinator fallback
has no new child to register.

## Binding and delivery

Supply labels before this adapter's first registration. The first observed
binding is sticky: if another observer has already registered a conflicting
label or parent, report the conflict. The transport has no supported override.
Repeated publication uses the same child identity; it cannot create a synthetic
replacement. An active display lost after receiver reset can be restored with
the same observed identity and original label. OpenRouter retains its separate external display ID and genuine
native parent association. Preserve its frozen declaration when taking over
through an approved native fallback.

The existing transport sends only bounded display metadata, never source,
prompts, raw outputs, credentials or reasoning. Readback checks the full label
and parent binding; actual rendering and accessibility need client observation.
Delivery, failure and display retirement never change execution, ownership,
acceptance or evidence. Continue ordinary work when optional visibility fails.
