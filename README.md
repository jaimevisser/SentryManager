# SentryManager

SentryManager is a web app for reviewing Tesla dashcam/Sentry footage, trimming events, switching camera layouts, and exporting a final rendered clip.

The UI is desktop-first. Mobile and narrow-screen layouts are not supported.

## Quick Start

Examples use `latest` for convenience. For reproducible deployments, pin a specific image tag.

Use the published image:

```bash
docker pull ghcr.io/jaimevisser/sentrymanager:latest
```

Run with your TeslaCam folder mounted at `/data/TeslaCam`:

```bash
docker run --rm -p 8765:8080 \
	-e TESLACAM_ROOT=/data/TeslaCam \
	-v /absolute/path/to/TeslaCam:/data/TeslaCam \
  ghcr.io/jaimevisser/sentrymanager:latest
```

Open http://localhost:8765

## Docker Compose Example

```yaml
services:
  app:
    image: ghcr.io/jaimevisser/sentrymanager:latest
    ports:
      - "8765:8080"
    environment:
      TESLACAM_ROOT: /data/TeslaCam
      SENTRY_PLAYER_PREROLL_SECONDS: 20
    volumes:
      - /absolute/path/to/TeslaCam:/data/TeslaCam
```

Start:

```bash
docker compose up -d
```

Stop:

```bash
docker compose down
```

Need a specific pinned version instead of `latest`? See [published image tags](https://github.com/jaimevisser/SentryManager/pkgs/container/sentrymanager).

## What The App Needs

- A writable TeslaCam mount at `/data/TeslaCam`.
- Event folders containing Tesla dashcam MP4 clips (including `SavedClips` and `SentryClips` layouts).

The app writes processing and edit artifacts back into event folders (for example telemetry sidecars, `sentrymanager.json`, render plans, and exported videos).

## Environment Variables

- `TESLACAM_ROOT`: In-container TeslaCam path. Default: `/data/TeslaCam`.
- `PORT`: Gunicorn bind port in container. Default: `8080`.
- `RENDER_WORKER_ENABLED`: Enable in-container background export worker. Default: `true`.
- `RENDER_WORKER_POLL_INTERVAL_SECONDS`: Worker poll interval. Default: `1.0`.
- `SENTRY_PLAYER_PREROLL_SECONDS`: Default lead-in when opening Sentry events without a saved non-zero trim start. Default: `20`.

## Related Docs

- `DEVELOPMENT.md`: architecture, internal notes, roadmap, and contributor validation commands.
- `docs/brief.md`: product scope and workflow.
- `docs/data.md`: data model and persisted artifacts.
- `TODO.md`: outstanding work.
