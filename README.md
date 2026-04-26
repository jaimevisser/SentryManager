# SentryManager

SentryManager is a web application for reviewing Tesla dashcam and Sentry Mode footage, assembling multi-angle edits, and exporting curated clips into a single rendered video.

The project is designed around a Python backend that serves Jinja-rendered HTML plus static JavaScript and CSS. The browser handles review and editing workflows, while heavier media work such as indexing, proxy generation, and final render orchestration will happen on the backend with tools such as `ffprobe` and `ffmpeg`.

## Goals

- Review TeslaCam events as a unified timeline instead of browsing loose clip fragments.
- Scrub through synchronized multi-angle footage in the browser.
- Mark ranges on the master event timeline and choose which camera view or layout should appear for each range.
- Export the final cut from the original footage, not from browser playback proxies.
- Run cleanly inside a Docker-based stack with a read-only TeslaCam volume mounted into the container.

## Current Scope

This initial scaffold provides:

- A Flask application with Jinja templates and static assets.
- A landing page that surfaces the mounted TeslaCam root and a lightweight event summary.
- Project documentation for product direction, data model, and execution plan.
- Docker and Compose files for local development and stack integration.

It does not yet provide:

- Persistent clip indexing.
- Proxy generation.
- Timeline editing.
- Final export jobs.
- Authentication or multi-user support.

## Architecture

### Backend

- Python 3.12
- Flask for HTTP routing and Jinja template rendering
- Gunicorn as the production container entrypoint
- Future media tooling via `ffprobe` and `ffmpeg`

### Frontend

- Server-rendered HTML templates
- Plain JavaScript modules in `app/static/js`
- Project CSS in `app/static/css`

### Media Workflow Direction

The intended workflow is:

1. Scan TeslaCam footage from a mounted volume.
2. Group short source clips into events and camera-angle timelines.
3. Generate lower-resolution proxy videos per angle per event for responsive review.
4. Let the user create edit decisions against the master event timeline.
5. Translate those edit decisions back onto original clips for final `ffmpeg` export.

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
│   ├── main.py
│   ├── static/
│   │   ├── css/common.css
│   │   └── js/app.js
│   └── templates/
│       ├── base.html
│       └── index.html
├── docker-compose.yml
├── docs/
│   ├── brief.md
│   └── data.md
└── requirements.txt
```

## Running With Docker Compose

The Compose file mounts these host folders into the container:

- `./config` to `/app/config`
- `./data/TeslaCam` to `/data/TeslaCam`
- `./data/Thumbnails` to `/data/Thumbnails`
- `./data/Previews` to `/data/Previews`

### Start the app

```bash
TESLACAM_PATH=/absolute/path/to/TeslaCam docker compose up --build
```

The app will then be available at `http://localhost:8765`.

If you do not set `TESLACAM_PATH`, Compose falls back to `./data/TeslaCam`.

### Stop the app

```bash
docker compose down
```

## Environment Variables

- `APP_ENV`: Logical environment name for the app. Defaults to `development`.
- `TESLACAM_ROOT`: In-container path to the TeslaCam footage root. Defaults to `/data/TeslaCam`.
- `THUMBNAILS_ROOT`: In-container path to generated thumbnails. Defaults to `/data/Thumbnails`.
- `PREVIEWS_ROOT`: In-container path to generated previews. Defaults to `/data/Previews`.
- `MAX_THUMBNAIL_FOLDER_SIZE_GB`: Fallback limit for the thumbnails folder. Defaults to `20`.
- `MAX_PREVIEWS_FOLDER_SIZE_GB`: Fallback limit for the previews folder. Defaults to `100`.
- `PORT`: Gunicorn bind port. Defaults to `8080`.

Compose publishes the app on host port `8765` by default while the container continues to listen on `8080` internally.

`/data/Thumbnails` and `/data/Previews` are also mounted for generated image thumbnails and prerendered full-camera previews.

## Configuration

The app now follows the same basic pattern used in 3dfabs: a checked-in example YAML under `config/`, plus an optional ignored local override file, loaded into a typed settings object at startup and then copied into Flask config.

Tracked defaults live in `config/general/config.example.yaml`:

```yaml
app_env: development
storage:
	max_thumbnail_folder_size_gb: 20
	max_previews_folder_size_gb: 100
```

For local or test-specific overrides, create `config/general/config.yaml`. It is ignored by git and layered on top of the example config at runtime.

The current config surface includes:

- maximum thumbnail folder size in GB
- maximum previews folder size in GB

Path settings stay in environment variables and Compose mounts rather than the YAML config.

If a YAML key is omitted, the matching environment variable is used as a fallback.

## TeslaCam Assumptions

The project assumes footage arrives as many short MP4 clips organized by event or by TeslaCam category folders such as `SavedClips`, `SentryClips`, or similar structures.

The starter page performs only a shallow summary so the app can boot against real footage without requiring the ingest pipeline to be complete.

## Development Notes

- Keep the browser experience server-rendered unless a specific interaction benefits from client-side enhancement.
- Treat footage on disk as the source of truth.
- Store edit decisions against a normalized event timeline so proxy playback and final export remain aligned.
- Use proxies only for review. Final output should always render from original clips.

## Validation Commands

Useful early validation commands:

```bash
python -m compileall app
docker compose config
docker build -t sentrymanager .
```

## Related Docs

- `docs/brief.md`: product scope and user workflow
- `docs/data.md`: initial data model and render concepts
- `TODO.md`: delivery plan in discrete steps
