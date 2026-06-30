# SentryManager

SentryManager is a web application for reviewing Tesla dashcam and Sentry Mode footage, assembling multi-angle edits, and exporting curated clips into a single rendered video.

The current UI is desktop-only for now. Narrow-screen and mobile layouts are not supported yet.

The project uses a Python backend that serves Jinja-rendered HTML plus static JavaScript and CSS. The browser handles review and editing directly against original event clips, while the backend handles discovery helpers, telemetry extraction, render-plan generation, and in-container background exports via `ffprobe` and `ffmpeg`.

## Goals

- Review TeslaCam events as a unified timeline instead of browsing loose clip fragments.
- Scrub through synchronized multi-angle footage in the browser.
- Mark ranges on the master event timeline and choose which camera view or layout should appear for each range.
- Export the final cut from the original footage.
- Run cleanly inside a Docker-based stack with a mounted TeslaCam volume available to the container.

## Current Functionality

- Discover TeslaCam events from direct event folders plus compatible one- and two-level category layouts.
- Build in-memory event summaries from filenames, `event.json`, thumbnails, telemetry sidecars, and `sentrymanager.json` markers.
- Browse events by day with thumbnails, category chips, location metadata, and trigger-aware defaults.
- Review synchronized source clips in single, double, and triple camera layouts with master-timeline scrubbing.
- Show telemetry overlays for speed, blinkers, brake state, autopilot state, and event-level `fsdOnPercent`.
- Persist trim handles, a saved start marker, and camera markers in `sentrymanager.json`, then normalize them into contiguous `normalizedEditSegments`.
- Generate render plans from normalized edit segments and queue background export jobs that render directly from original source clips.
- Surface export readiness, active job state, and latest output or failure details in the player.
- Run browser-versus-export render-snapshot regression coverage against real `SavedClips` fixtures.

## Still Missing

- Persistent normalized indexing beyond the current on-demand event summaries.
- Timeline gap surfacing for missing camera coverage.
- Higher-level segment editing such as split, merge, retime, labels, notes, and playback-rate overrides.
- Full browser/export parity for every layout and overlay edge case.
- Export progress reporting, storage management, structured logging, deployment health checks, and backup guidance.
- Authentication and multi-user support.

## Architecture

### Backend

- Python 3.12
- Flask for HTTP routing and Jinja template rendering
- Gunicorn as the production container entrypoint
- `ffprobe` and `ffmpeg` for clip probing and export rendering
- File-backed render jobs processed by a daemon thread in the app container

### Frontend

- Server-rendered HTML templates
- Plain JavaScript modules in `app/frontend/static/js`
- Project CSS in `app/frontend/static/css`

### Media Workflow

The current workflow is:

1. Scan TeslaCam footage from a mounted volume.
2. Group short source clips into events and camera-angle timelines.
3. Generate telemetry sidecars and event markers as needed.
4. Review synchronized source clips directly in the browser.
5. Persist edit decisions in `sentrymanager.json` and normalize them into export segments.
6. Generate a render plan and render the final cut from original clips.

## Repository Layout

```text
.
├── AGENTS.md
├── Dockerfile
├── README.md
├── TODO.md
├── config/
│   └── general/config.example.yaml
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── frontend/
│   │   ├── app.py
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

## Running With Docker Compose

The Compose file mounts these host folders into the container:

- `./config` to `/app/config`
- `./data/TeslaCam` to `/data/TeslaCam`

`/data/TeslaCam` must be writable by the container so the app can store segment-level `-telemetry.sei.bin` files, `sentrymanager.json` processing data, render plans, and rendered exports inside event folders.

### Start the app

```bash
TESLACAM_PATH=/absolute/path/to/TeslaCam docker compose up --build app
```

The app will then be available at `http://localhost:8765`.

If you do not set `TESLACAM_PATH`, Compose falls back to `./data/TeslaCam`.

### Stop the stack

```bash
docker compose down
```

## Environment Variables

- `APP_ENV`: Logical environment name for the app. Defaults to `development`.
- `TESLACAM_ROOT`: In-container path to the TeslaCam footage root. Defaults to `/data/TeslaCam`.
- `PORT`: Gunicorn bind port. Defaults to `8080`.
- `RENDER_WORKER_ENABLED`: Starts the background render worker thread inside the app container. Defaults to `true`.
- `RENDER_WORKER_POLL_INTERVAL_SECONDS`: Poll interval for the in-container render worker. Defaults to `1.0`.

Compose publishes the app on host port `8765` by default while the container continues to listen on `8080` internally.

## Configuration

The app now follows the same basic pattern used in 3dfabs: a checked-in example YAML under `config/`, plus an optional ignored local override file, loaded into a typed settings object at startup and then copied into Flask config.

Tracked defaults live in `config/general/config.example.yaml`:

```yaml
app_env: development
```

For local or test-specific overrides, create `config/general/config.yaml`. It is ignored by git and layered on top of the example config at runtime.

The current config surface includes:

- app environment selection

Path settings stay in environment variables and Compose mounts rather than the YAML config.

If a YAML key is omitted, the matching environment variable is used as a fallback.

## TeslaCam Assumptions

The project assumes footage arrives as many short MP4 clips organized by event folders or TeslaCam category folders such as `SavedClips` and `SentryClips`, including compatible nested layouts.

The current app discovers events on demand and keeps summaries in memory rather than in a persistent index.

## Development Notes

- Keep the browser experience server-rendered unless a specific interaction benefits from client-side enhancement.
- Treat footage on disk as the source of truth.
- Store edit decisions against a normalized event timeline so playback and final export remain aligned.

## Validation Commands

Useful early validation commands:

```bash
python -m compileall app
docker compose config
docker build -t sentrymanager .
```

## Published Image

Pushes to `master` trigger GitHub Actions to build and publish the Docker image to `ghcr.io/jaimevisser/sentrymanager`.

Published tags are:

- `latest`
- `YYYY.MM.B`, where `B` auto-increments from existing tags in the same UTC month

## Related Docs

- `docs/brief.md`: product scope and user workflow
- `docs/data.md`: current persisted artifacts plus core data model terms
- `TODO.md`: remaining delivery work
