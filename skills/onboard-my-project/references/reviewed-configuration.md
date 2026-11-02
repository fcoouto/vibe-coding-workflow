# Reviewed Configuration

Load this reference when presenting the reviewed onboarding proposal or updating its user-facing status. Follow [onboarding authority](../../../policies/10-project-onboarding.md#onboarding-authority); this document explains the work and does not authenticate or expand consent.

Write a readable Markdown file beside the private plan, outside source control and instruction discovery. Link it in the user response. Use the real project name, scope, paths, decisions and observations. Keep the complete machine-readable plan, exact proposed contents and recovery records authoritative; do not create another status store.

Explain the following when relevant, using short paragraphs or a small table:

- **Scope:** selected project, checkout and clients; preserve the user's existing choices.
- **Changes:** each concrete path or resource, what changes and why. Link large exact proposals rather than pasting JSON or hashes into the summary.
- **Next:** the next authorized action, checks and remaining prerequisites. Do not turn internal transaction stages into user approval steps.
- **Decisions needed:** only unresolved material exceptions. Say “None” when none remain. Describe each exception, its consequence and recommendation; identify the dependent work that waits.
- **Status:** what has actually completed and what remains. Distinguish completed file configuration from an active workflow. Say that activation is pending when required proof is missing; never translate a successful helper exit into native qualification.
- **Recovery:** what can resume or be undone, which later edits or uncertain ownership will be preserved, and any limit that affects the user. Link exact recovery instructions and retained records; do not promise lossless recovery without those records.
- **Technical records:** direct links to the concrete plan, proposed file contents, check results and recovery material. Keep internal stage codes, schema fields, digests and receipt identifiers here.

Do not show credentials, raw transcripts or secret contents. Omit irrelevant sections and avoid repeating the full coverage matrix. Retain material blockers and limitations even when the normal path is simple. A technical status may be translated into ordinary language only when its meaning remains exact.

## Example

This illustrates wording, not a plan or approval for any real project. Replace example paths and technical references with actual supported links before presenting a real document.

> # Reviewed Configuration — Example project
>
> **Scope:** Set up this checkout in Codex, preserving existing project settings.
>
> **Changes:** Add the project setup guide at `docs/setup.md` and the project registration at `.vibe-coding-workflow/project.json`. Keep private recovery records beside the setup plan.
>
> **Next:** Apply these changes, run the required checks, and enable the agreed workflow once those checks qualify. Create runtime state only when the selected managed operation needs it.
>
> **Decisions needed:** None. The onboarding request covers these effects.
>
> **Status:** The configuration has been reviewed. Application, checks and activation remain.
>
> **Recovery:** Resume from the recorded step after interruption. Undo only changes still matching this operation's results; preserve later edits.
>
> **Technical records:** The real document links its exact proposed contents, checks and recovery instructions here.
