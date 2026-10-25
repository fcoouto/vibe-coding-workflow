# Development rules

- Wrap the full Vibe Coding Toolkit; preserve its scope and requirements.
- Reference current upstream procedures instead of maintaining copied prompts.
- Keep each skill entry point within 150 words. Define each wrapper rule once.
- Keep environment preparation, project enrollment, and routine development distinct.
- Preserve the user's permissions, model choices, subscriptions, and customizations.
- Validate with `python3 -B scripts/validate.py`.
- Create release archives only when requested.
- Report package validation and observed client execution separately.

## Instruction authoring

- Use OpenAI's `skill-creator` as the standard when creating or changing skills and workflow instructions.
- Keep purpose, essential constraints, and explicit loading triggers in entry points. Load detailed procedures only when applicable, including every source those procedures require.
- Preserve every requirement when shortening or reorganizing instructions. Keep each requirement traceable to its authoritative source and applicable procedure.
- Check affected instruction paths with representative tasks: required procedures load, every applicable requirement is satisfied, and unrelated material stays unloaded. Word counts and package validation alone do not prove behavior.
- Write human-facing guidance in plain language: explain purpose, next action, and what completion means.
