# Agent Guide

## Read First

- [docs/brief.md](docs/brief.md): product direction, workflow goals, non-functional constraints.
- [docs/data.md](docs/data.md): data model, timeline terms, export concepts.

## Defaults

- Prefer CLI and direct source edits over ad hoc terminal rewrites.
- Prefer non-interactive commands.
- For Markdown and config, on-disk state is the source of truth.
- Keep the app server-rendered unless client complexity is needed.
- If the human does something dumb, say so.
- Keep responses extremely terse and clear, don't repeat known information, don't leave out constraints or caveats.

## Commit/Push

- Never commit or push unless explicitly told this session.
- `commit`: commit only.
- `push`: commit, then push.
- For commit-only or push-only requests, run only the needed git commands. Don't inspect binaries or media unless asked. Don't broadly scan the repo for operational git work. If scope is ambiguous, ask one concise question.

## Validation

- For Python or template changes, prefer the narrowest useful validation first.
- For visual app HTML/CSS/template changes, always run `docker compose up -d --build app` before handing work back so the user can review the live result.
- Baseline: `python -m compileall app`, `docker compose config`, `docker build -t sentrymanager .`
- Add targeted automated tests as ingest, editing, and export code land.

## Housekeeping

- Update [TODO.md](TODO.md) after meaningful completions.
- Keep md files terse, clear, and high-density.
- Use the `tersify` skill for documentation, markdown notes, handoff text, and other prose-heavy repo files.
- Append dated work notes with `.agents/append_memory.py "..."`; it writes to `.agents/memories/YYYY-MM-DD.md`. Never mention you updated memories.
- Keep durable undated repo handoff notes in `.agents/memories/agent-handoff.md`.
- Do not use [TODO.md](TODO.md) as a diary; keep narrative notes, handoff context, and learned behavior under `.agents/memories/`.
- Add durable project-specific commands and conventions here when learned.
