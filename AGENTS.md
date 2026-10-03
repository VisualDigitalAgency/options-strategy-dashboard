# AGENTS.md

Global rules for every AI agent working in this repository (Claude Code, Codex, Cursor, Copilot and others). Project-specific guidance lives in CLAUDE.md, CONTRIBUTING.md and SECURITY.md.

## Working rules

### Core behavior
1. Don't assume. Don't hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.

### How the owner works
- Plan before build: confirm the approach in chat before generating files.
- Execution-ready output, not outlines or scaffolds.
- When iterating, make targeted corrections; don't rewrite the whole thing.

### Communication
- Ask before assuming scope on ambiguous requests.
- If a task needs more than ~3 file changes, outline the plan first.
- Flag uncertainty rather than picking silently.

### Skills (vendored in `.claude/skills/`)
Pick by the nature of the task, every time, without being asked:
- Development (writing, fixing, refactoring or reviewing code; choosing libraries): use `ponytail`, the simplest change that works. Use `ponytail-review` to review a diff for over-engineering.
- Design (pages, components, layout, styling, accessibility, UX copy): use `ui-ux-pro-max`. Its search tool runs as `python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain>`.
- A task that is both (e.g. a new page): use both, `ui-ux-pro-max` for the design and `ponytail` for the code.
- Agents without a skill loader (Codex, Cursor, Copilot) read the skill's `SKILL.md` and follow it.
- Simplicity never removes a security check, a validation, or a test this repo requires (SECURITY.md, `rpc_guard`, RLS).

### Never
- Never touch `.env`, `secrets/`, or credentials files without asking.
- Never `git push --force` without explicit confirmation.
- Never delete files outside the current task's scope.
