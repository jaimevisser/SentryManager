# Agent Guide

## Read First

- [docs/brief.md](docs/brief.md): product direction, workflow goals, non-functional constraints.
- [docs/data.md](docs/data.md): data model, timeline terms, export concepts.

## Defaults

- Prefer CLI and direct source edits over ad hoc terminal rewrites.
- Prefer non-interactive commands; avoid prompts.
- For Markdown and config, on-disk state is the source of truth.
- Keep the app server-rendered unless client-side complexity is needed.

## Commit/Push

- Never commit or push unless explicitly told this session.
- `commit`: don't push.
- `push`: commit, then push.
- For commit-only or push-only requests: run only required git commands; don't inspect binaries or media unless asked; don't broadly scan the repo for purely operational git work; if commit scope is ambiguous, ask one concise question.

## Validation

- For Python or template changes, prefer the narrowest useful validation first.
- For visual app HTML/CSS/template changes, always run `docker compose up -d --build app` before handing work back so the user can review the live result.
- Baseline: `python -m compileall app`, `docker compose config`, `docker build -t sentrymanager .`
- Add targeted automated tests as ingest, proxy, and export code lands.

## Housekeeping

- Update [TODO.md](TODO.md) after meaningful completions.
- Add durable project-specific commands or conventions here when learned.
