# Diary
Add new stuff at the bottom. Keep sections per date. Add times to entries.

## Agent Handoff

- The repo now has a working Flask review app with grouped event browsing, an event player, plain-JS controls, Docker/Compose wiring, typed config loading, and project docs.
- Compose publishes the app on `8765`, mounts TeslaCam footage at `/data/TeslaCam`, and can write telemetry sidecars plus `sentrymanager.json` markers back into event folders.
- Event discovery scans direct event folders plus one- and two-level TeslaCam layouts, caches summaries, and enriches cards from `event.json`, `thumb.png`, and `sentrymanager.json`.
- The review UI supports grouped browsing, thumbnails, location/category chips, trigger-aware Sentry defaults, synchronized clip progression, composite camera views, and telemetry-backed speed, blinker, and autopilot indicators.
- The Flask UI now lives under `app/frontend/`; render normalization and plan generation live under `app/renderer/`.
- Player edits support trim handles, a saved start marker, and camera markers. Saved edits are normalized into contiguous `normalizedEditSegments` in `sentrymanager.json`.
- The renderer probes clips with `ffprobe`, builds declarative plans from normalized segments, and runs queued jobs in the `worker` service via `.sentrymanager/render-jobs`.
- `tests/test_renderer_pipeline.py` covers edit normalization plus render-plan generation across clip boundaries and missing-camera cases without invoking `ffmpeg`.
- The app container now includes `ffmpeg`, and queued export plus latest-download flow was validated end to end against `SavedClips/2026-03-28_09-12-13`.
- Export telemetry now matches the browser more closely: it uses the browser safe-zone geometry, sizes heading arrows from the full safe zone, and uses bundled Tektur plus tracked text and glow for the right-corner speed unit and FSD label.
- A Playwright render-snapshot suite compares deterministic browser frames against export frames for left blinker, right blinker, brake, and blue-FSD fixtures from real `SavedClips` footage; the snapshot hook waits for initial seeks to settle.
- Failed render jobs now store short sanitized summaries instead of raw `ffmpeg` stderr, and the player UI caps long render status strings.
- Double-layout export slots now force even widths, fixing `ffmpeg pad` failures on yuv420p exports that otherwise split the 1920px stage into two 941px columns.
- Added the `tersify` skill under `.github/skills/tersify/`, used it to compact its own prompt after a duplicate-body edit, and tersified `AGENTS.md` without dropping workflow constraints.

### 2026-05-01
- 20:23 Removed completed work from `TODO.md` and moved current functionality notes into `README.md`, `docs/brief.md`, and `docs/data.md`.
- 20:27 Refreshed `docs/data.md` against the code so it documents the real `sentrymanager.json`, `playerEdits`, normalized segments, playlists, media index, render jobs, and render-plan fields.
- 20:36 Tersified `docs/brief.md`, removed duplicated implementation detail, and pointed readers to `README.md`, `docs/data.md`, and `TODO.md` for current state.
- 20:39 Tersified `docs/sei-metadata.md` and updated it with current code-path behavior, including event-page sidecar generation, segment-level sidecar naming, marker updates, and the packed binary column format.
- 20:51 Changed driver-assist percentage display to prefer `FSD` only for `SELF_DRIVING`, fall back to `AP` for `AUTOSTEER` plus `TACC`, and threaded that mode-aware label through both stage and export rendering.
- 21:02 Refactored the main readability hotspots: extracted Flask event-path and event-player context helpers in `app/frontend/app.py`, split render-plan assembly/output helpers in `app/renderer/pipeline.py`, and moved pure player-page utilities into new `app/frontend/static/js/event_player-page-helpers.js`.
- 21:02 Validation: `python3 -m compileall app`, `node --check app/frontend/static/js/event_player-page.js`, `node --check app/frontend/static/js/event_player-page-helpers.js`, `docker compose up -d --build app`, and browser smoke checks for `/` plus `/events/SavedClips/2026-03-28_09-12-13`.
- 21:02 Found a leftover maintenance target during the review: the repo still has a parallel `app/static` and `app/templates` tree beside the active `app/frontend` assets/templates, so `TODO.md` now tracks deciding whether to remove or realign it.

### 2026-05-02
- 15:23 Confirmed Flask serves assets and templates from `app/frontend` because `app/frontend/app.py` builds `Flask(__name__)` without overriding `static_folder` or `template_folder`; inside the container, `app.root_path` resolved to `/app/app/frontend` and `app.static_folder` to `/app/app/frontend/static`.
- 15:23 Removed the unused legacy `app/static` and `app/templates` files and empty directories, and cleared the matching cleanup item from `TODO.md`.
- 15:29 Fixed slow index-to-player navigation for cached events: `ensure_sei_sidecars()` was reparsing front-camera MP4 SEI on every player load before checking whether each `*-telemetry.sei.bin` already existed. It now trusts existing sidecars plus complete `sentrymanager.json` event flags and skips the rebuild path.
- 15:29 Validation: `docker compose up -d --build app`, `docker compose exec app python -m compileall /app/app`, `curl` to `/events/SavedClips/2026-03-31_06-53-21` before and after (`~0.96s` to `~0.06s` TTFB), and a browser smoke click from `/` into the March 31 player.
- 17:48 Changed indexing ownership so `sentrymanager.json` is now the sole indexed marker: if it exists, the app assumes indexing is done; if it does not, `/` and direct player loads enqueue the event for a daemon background worker that builds SEI sidecars and then writes the marker.
- 17:48 Removed synchronous indexing from player-page load, stopped player-load normalization from creating `sentrymanager.json` early, and made save/export routes return `409` plus requeue when indexing is still pending.
- 17:48 Validation: mounted-container unit tests for `test_sei.py` and new `test_frontend_app.py`, `docker compose up -d --build app`, `docker compose exec app python -m compileall /app/app`, `curl` TTFB checks for `/` and `/events/SavedClips/2026-03-31_06-53-21` (`~0.056s` and `~0.048s`), and browser smoke navigation from `/` into the March 31 player.
- 17:55 Moved render-job execution into the app container: `create_app()` now starts a daemon render worker thread beside the event-indexing worker, `docker-compose.yml` defaults to a single `app` service, and the standalone worker service was dropped from the default stack.
- 17:55 Validation: mounted-container tests for `test_frontend_app.py`, new `test_renderer_worker.py`, and `test_renderer_jobs.py`; `docker compose config`; `docker compose up -d --build --remove-orphans app`; and a live render enqueue on `SavedClips/2026-03-31_06-53-21` that advanced from `queued` to `running` without any separate worker container.
- 18:34 Split `app/frontend/static/js/event_player-page.js` along real responsibilities instead of adding more inline helpers: extracted snapshot/test hooks into `event_player-page-snapshot.js`, stage safe-zone geometry into `event_player-page-stage.js`, and telemetry HUD sync into `event_player-page-hud.js`. The main page controller dropped from 2611 to 2170 lines.
- 18:34 Validation: `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep "saved-brake"` after each extraction step; caught and fixed a broken import/config-block edit during the stage split, then re-ran to a clean pass.
- 19:12 Finished the remaining player split by extracting export/persistence, playback/load coordination, and editing/timeline behavior into `event_player-page-export.js`, `event_player-page-playback.js`, and `event_player-page-editing.js`, then rebuilt `event_player-page.js` as a clean composition root after a failed incremental rewiring left the file corrupted.
- 19:12 Validation: `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep "saved-brake"` passed after the rebuild; final module sizes are 729 lines for `event_player-page.js`, 968 for editing, 550 for playback, 314 for export, 246 for snapshot, 183 for HUD, and 141 for stage.
- 21:45 Continued the readability pass by extracting Flask route registration into new `app/frontend/routes.py`, leaving `create_app()` as setup plus registration, and by moving event-player bootstrap parsing, DOM lookup, and preload-video setup into new `app/frontend/static/js/event_player-page-bootstrap.js`.
- 21:45 Validation: `docker compose up -d --build app`, `docker run --rm -v "$PWD:/work" -w /work sentrymanager-app python -m unittest discover -s tests -p 'test_frontend_app.py'`, `docker compose exec app python -m compileall /app/app`, `node --check app/frontend/static/js/event_player-page.js`, `node --check app/frontend/static/js/event_player-page-bootstrap.js`, and `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep 'saved-brake'`.
- 21:45 Size snapshot: `app/frontend/app.py` is now 807 lines, `app/frontend/routes.py` is 211 lines, `app/frontend/static/js/event_player-page.js` is 694 lines, and `app/frontend/static/js/event_player-page-bootstrap.js` is 112 lines.
- 14:03 Extracted the camera-marker and start-marker popover DOM behavior out of `app/frontend/static/js/event_player-page-editing.js` into new `app/frontend/static/js/event_player-page-marker-ui.js`, leaving the editing controller focused on edit state, playback marker logic, and trim rules instead of DOM construction plus pointer wiring.
- 14:03 Validation: `node --check app/frontend/static/js/event_player-page-editing.js`, `node --check app/frontend/static/js/event_player-page-marker-ui.js`, and `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep 'saved-brake'`.
- 14:03 Size snapshot: `app/frontend/static/js/event_player-page-editing.js` is now 607 lines and `app/frontend/static/js/event_player-page-marker-ui.js` is 413 lines.

### 2026-05-03
- 16:37 Fixed successful render retention so `app/renderer/pipeline.py` now prunes older exported `.mp4` files, older `.render-plan.json` files, and all timestamped `*-segments` directories after a new export finishes.
- 16:37 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 19:24 Fixed render-job retention so `app/renderer/jobs.py` now prunes older `succeeded` job records for the same event as soon as a newer success is recorded, while leaving other events' job history alone.
- 19:24 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_jobs.py'`.
- 20:01 Manually removed 61 historical `*-segments` directories from `data/TeslaCam/SavedClips/2026-03-28_09-12-13/exports` after confirming they predated the new automatic cleanup path and the running app container had not yet been rebuilt with it.
- 20:04 Rebuilt and restarted the `app` service with `docker compose up -d --build app`, so the live container now runs the new export and succeeded-job cleanup code instead of the older baked image.
- 12:37 Adjusted only `app/frontend/static/images/sentry-eye-small.svg` to use sparser 30-degree rays for better legibility at small sizes; restored `sentry-eye.svg` and `sentry-eye-background.svg` to the original dense spoke pattern after an over-broad first pass.

### 2026-06-30
- 12:00 Added `.github/workflows/publish-docker.yml` so pushes to `master` publish `ghcr.io/jaimevisser/sentrymanager` with `latest` plus a `YYYY.MM.B` tag computed from existing GHCR tags for the current UTC month; workflow serialization avoids duplicate monthly build numbers on overlapping pushes.

### 2026-07-01
- 00:05 Removed the unused YAML config subsystem entirely: deleted `app/config.py` plus `config/general/*`, dropped the Compose config mount and Docker `COPY config`, removed `PyYAML`, and switched app startup back to a direct `TESLACAM_ROOT` environment default.
- 06:20 Reduced the player trim minimum from 60 seconds to 5 seconds in `app/frontend/static/js/event_player-page-editing.js`, while keeping the existing shorter-than-total-duration fallback for events under the minimum.
- 06:20 Validation: `node --check app/frontend/static/js/event_player-page-editing.js` and `npx playwright test tests/trim_duration.spec.js --reporter=line`.
- 07:03 Moved event location text into a new top-left stage safe-zone overlay in the player (`data-player-safe-zone="top-left"`), kept the existing bottom telemetry zones unchanged, and removed location text from the player meta line above the stage.
- 07:03 Added top-left safe-zone geometry support to stage helpers/controller and a focused Playwright regression at `tests/location_safe_zone.spec.js`.
- 07:03 Validation blocked: `docker compose up -d --build app` failed pulling `python:3.12-slim` metadata from Docker Hub with `context deadline exceeded`, so browser verification of the rebuilt container could not complete in this run.
- 07:29 Centered the top-left location text inside its safe zone in the viewer and extended the export telemetry overlay pipeline to draw the same location label in the top-left safe zone (bottom-aligned in that zone), including top-corner safe-zone geometry and truncation-to-fit handling for long labels.
- 07:29 Validation: `docker compose up -d --build app`, `npx playwright test tests/location_safe_zone.spec.js --reporter=line`, and `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 07:48 Moved date and time into the same top-left safe zone as location and switched the overlay format to three centered lines: `DD-MM-YYYY`, `HH:MM`, and location; removed the old date/time strip above the player stage.
- 07:48 Extended export overlays to draw the same three-line top-left block by deriving date/time from `event.json` timestamp (with event-folder timestamp fallback) and location from `event.json` street/city.
- 07:48 Validation: `docker compose up -d --build app`, `npx playwright test tests/location_safe_zone.spec.js --reporter=line`, and `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 08:02 Increased top-left export text readability and then set that block to explicit pure white with no shadow; validated with `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'` and `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep 'saved-left-blinker'`.
- 08:12 Removed renderer shadow treatment for export overlays (text and icon drop-shadow path), while preserving existing semantic colors such as the black heading letter inside the navigation icon.
- 08:12 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'` and `npx playwright test tests/render_snapshot.spec.js --reporter=line --grep 'saved-left-blinker'`.
- 08:18 Removed the leftover empty gray band above the player stage by clearing `margin-top` on `.player-stage-single`; validated with `docker compose up -d --build app` and `npx playwright test tests/location_safe_zone.spec.js --reporter=line`.
- 08:24 Removed the final top spacing from `.page-shell-full` so the fullscreen player sits flush under the header; revalidated with `docker compose up -d --build app` and `npx playwright test tests/location_safe_zone.spec.js --reporter=line`.
- 08:41 Changed the top-left date/time overlay to track timeline progress instead of staying fixed: viewer now computes labels from `eventTimestampIso + current event time`, and export overlays now compute labels per frame from base event timestamp plus timeline offset.
- 08:41 Validation: `docker compose up -d --build app`, `npx playwright test tests/location_safe_zone.spec.js --reporter=line`, and `python3 -m compileall app`.
- 08:41 Renderer test environment note: `docker compose run --rm app pytest ...` and `docker compose run --rm app python -m pytest ...` both failed because `pytest` is not installed in the app image.
- 08:45 Renderer validation completed with mounted-source unittest path: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'` (9 passed).
- 09:02 Added `sentry-eye-small.svg` to the export-only top-left safe zone, centered above the date/time/location stack in renderer output while leaving stage/viewer overlays unchanged.
- 09:02 Validation: `docker compose up -d --build app` and `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 09:06 Increased the export top-left eye icon target size to 50% of safe-zone width while preserving aspect ratio through the existing renderer SVG scaling path.
- 09:06 Validation: `docker compose up -d --build app` and `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 09:10 Corrected the export top-left icon asset from `sentry-eye-small.svg` to `sentry-eye.svg` after visual review feedback; sizing remains 50% of safe-zone width.
- 09:10 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 09:14 Added a centered `SentryManager` label above the export top-left eye icon while keeping the date/time/location stack below it.
- 09:14 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_renderer_pipeline.py'`.
- 21:21 Updated `.github/workflows/publish-docker.yml` to publish a multi-arch GHCR image manifest for `linux/amd64`, `linux/arm64`, and `linux/arm/v7` (instead of amd64-only), adding QEMU setup so ARM variants can be built on the GitHub-hosted runner.
- 21:31 Investigated failed run `28542116791` via `gh run view --job 84618298363 --log`; root cause was `linux/arm/v7` building `Pillow` from source without system build headers (`zlib` missing). Updated `Dockerfile` apt packages to include `build-essential`, `zlib1g-dev`, `libjpeg62-turbo-dev`, and `libopenjp2-7-dev` so ARM source builds succeed.
- 21:31 Validation: `docker build -t sentrymanager:localfix .` completed successfully after the dependency change.
- 21:38 Confirmed the previously failing platform by running `docker buildx build --platform linux/arm/v7 -t sentrymanager:armv7-test --load .`; build completed (`exit_code:0`) and `Pillow` wheel compilation finished successfully on arm/v7.

### 2026-07-02
- 07:28 Fixed Sentry trigger-camera mapping in `app/frontend/app.py` so metadata camera IDs 3/5 and 4/6 are swapped to the correct side-pair perspectives (`3->left_pillar`, `5->left_repeater`, `4->right_pillar`, `6->right_repeater`).
- 07:28 Added a regression test in `tests/test_frontend_app.py` that writes `event.json` with camera IDs 3, 4, 5, and 6 and asserts the corrected `load_event_trigger_camera_key()` results.
- 07:28 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_frontend_app.py'` (4 passed).
- 08:19 Changed Sentry initial playback default lead-in from 60 seconds to a configurable env var: `SENTRY_PLAYER_PREROLL_SECONDS` now drives the fallback start-time offset and defaults to 20 seconds.
- 08:19 Wired the new env var into `docker-compose.yml` (`SENTRY_PLAYER_PREROLL_SECONDS: ${SENTRY_PLAYER_PREROLL_SECONDS:-20}`) and documented behavior in README Environment Variables.
- 08:19 Added frontend-app unit coverage for configurable and invalid `SENTRY_PLAYER_PREROLL_SECONDS` handling in `tests/test_frontend_app.py`.
- 08:19 Validation: `docker compose run --rm -v "$PWD/app:/app/app:ro" -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p 'test_frontend_app.py'` (6 passed), `python3 -m compileall app`, and `docker compose up -d --build app`.
- 09:02 Tersified `README.md` for end users and moved contributor/internal material (architecture, roadmap, workflow, publishing, validation) into new `DEVELOPMENT.md`.
- 09:02 README now assumes image-first usage with `ghcr.io/jaimevisser/sentrymanager:2026.07.8`, including both `docker run` and Compose examples that mount TeslaCam at `/data/TeslaCam`.
- 09:16 Replaced fixed image tag examples in `README.md` with `ghcr.io/jaimevisser/sentrymanager:latest` and added a direct link to the package page for users who want pinned version tags.
- 09:21 Added a brief README versioning policy note clarifying that examples use `latest` for convenience and that pinned tags are recommended for reproducible deployments; converted the package URL to a labeled markdown link.