# Development Notes

This document holds internal and contributor-facing information moved out of README.

## Architecture

### Backend

- Python 3.12
- Flask for routing and Jinja template rendering
- Gunicorn as container entrypoint
- `ffprobe` and `ffmpeg` for probing and export rendering
- File-backed render jobs processed by an in-container daemon worker

### Frontend

- Server-rendered HTML templates
- Plain JavaScript modules in `app/frontend/static/js`
- CSS in `app/frontend/static/css`

## Current Functionality

- Discover TeslaCam events from direct event folders and compatible one- and two-level category layouts.
- Build in-memory event summaries from filenames, `event.json`, thumbnails, telemetry sidecars, and `sentrymanager.json`.
- Browse events by day with thumbnails, category chips, location metadata, and trigger-aware defaults.
- Review synchronized clips in single, double, and triple camera layouts with master-timeline scrubbing.
- Show telemetry overlays for speed, blinkers, brake state, autopilot state, and event-level `fsdOnPercent`.
- Persist trim handles, saved start marker, and camera markers in `sentrymanager.json`, then normalize into contiguous `normalizedEditSegments`.
- Generate render plans from normalized segments and queue background exports from original source clips.
- Surface export readiness, active job state, and latest output or failure details in the player.
- Run browser-vs-export render-snapshot regression tests against real `SavedClips` fixtures.

## Roadmap / Not Yet Implemented

- Persistent normalized indexing beyond current on-demand in-memory summaries.
- Timeline gap surfacing for missing camera coverage.
- Higher-level segment editing: split, merge, retime, labels, notes, playback-rate overrides.
- Full browser/export parity for all layout and overlay edge cases.
- Better export progress reporting and storage/output lifecycle management.
- Structured logging, deployment health checks, and backup guidance.
- Authentication and multi-user support.

## Media Workflow

1. Scan TeslaCam footage from mounted storage.
2. Group short source clips into events and camera-angle timelines.
3. Generate telemetry sidecars and event markers as needed.
4. Review synchronized source clips in the browser.
5. Persist edits in `sentrymanager.json` and normalize into export segments.
6. Generate a render plan and render the final cut from original clips.

## Repository Layout

```text
.
├── AGENTS.md
├── DEVELOPMENT.md
├── Dockerfile
├── README.md
├── TODO.md
├── app/
│   ├── __init__.py
│   ├── frontend/
│   │   ├── app.py
│   │   ├── routes.py
│   │   ├── static/
│   │   └── templates/
│   ├── main.py
│   └── renderer/
│       ├── jobs.py
│       ├── pipeline.py
│       └── worker.py
├── docker-compose.yml
├── docs/
│   ├── brief.md
│   ├── data.md
│   ├── rendering_plan.md
│   └── sei-metadata.md
├── tests/
│   ├── render_snapshot.spec.js
│   ├── test_renderer_jobs.py
│   └── test_renderer_pipeline.py
└── requirements.txt
```

## Contributor Validation

Baseline checks:

```bash
python -m compileall app
docker compose config
docker build -t sentrymanager .
```

For visual app HTML/CSS/template changes, rebuild app service before handoff:

```bash
docker compose up -d --build app
```

## Image Publishing

- Pushes to `master` publish `ghcr.io/jaimevisser/sentrymanager`.
- Tag formats:
  - `latest`
  - `YYYY.MM.B` where `B` increments within the same UTC month

## Related Docs

- `docs/brief.md` for product direction and workflow.
- `docs/data.md` for data model and persisted artifacts.
- `TODO.md` for remaining work.
