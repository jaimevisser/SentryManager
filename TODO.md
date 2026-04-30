# TODO

## Agent handoff

- The repo now has a working Flask review app with a grouped event index, an event player, plain-JS playback controls, Docker/Compose wiring, typed config loading, and project docs.
- Compose publishes the app on host port `8765`, mounts TeslaCam footage at `/data/TeslaCam`, and the container can write segment telemetry sidecars plus `sentrymanager.json` markers back into event folders.
- Event discovery is broader than the original scaffold note implied: the index scans direct event folders plus one- and two-level TeslaCam layouts, caches in-memory summaries, and enriches cards from `event.json`, `thumb.png`, and `sentrymanager.json`.
- The review UI already supports grouped browsing, event thumbnails, location/category chips, trigger-aware Sentry defaults, synchronized clip progression, composite camera views, and telemetry-backed speed/blinker/autopilot indicators.
- The player now supports persisted trim handles, a saved start-marker view, and camera markers in each event's `sentrymanager.json`, but those edits are still stored as raw marker state rather than normalized timeline segments.
- There is still no durable ingest store, normalized edit-segment model, or export pipeline.
- The best next implementation slice is to normalize the saved marker state into contiguous edit segments, then persist the event, clip, coverage, and telemetry model in a local store so export can consume deterministic timeline data.

This file tracks the delivery plan for SentryManager as discrete implementation steps.

## Phase 1: Foundation

- [x] Create the initial Flask app structure with Jinja templates and static assets.
- [x] Add Docker and Compose files with a mounted TeslaCam footage volume.
- [x] Write the core project documentation and agent guidance.
- [x] Add basic application configuration management for local, test, and production environments.

## Phase 2: Discovery And Ingest

- [x] Discover TeslaCam event directories from the root, category folders, and compatible nested layouts.
- [x] Build in-memory event summaries from filenames, `event.json`, thumbnails, and `sentrymanager.json` markers.
- [x] Group raw clips into angle-specific playlists for the review UI.
- [x] Document upstream Tesla SEI metadata support and field inventory for compatible clips.
- [x] Generate per-segment `-telemetry.sei.bin` sidecars in a frontend-ready binary format.
- [x] Extract and use the clip metadata needed for review playback from filenames, browser media metadata, `event.json`, and telemetry sidecars.
- [x] Record event-level `fsdOnPercent` in `sentrymanager.json` when SEI autopilot state metadata is available.
- [ ] Persist normalized event, clip, and telemetry metadata in a local data store.
- [ ] Represent missing-angle coverage explicitly in the normalized event model.

## Phase 3: Review UI

- [x] Build an event browser that lists detected TeslaCam sessions.
- [x] Group events by day and surface thumbnails, category chips, and location metadata when available.
- [x] Choose a useful default Sentry view and initial playback offset from `event.json` trigger metadata when available.
- [x] Show street and city metadata from `event.json` on event thumbnail tiles when available.
- [x] Add an event player linked from the browser, with sequential clip playback and switchable camera views.
- [x] Add synchronized multi-angle composite playback for front, rear, and side layouts when source clips exist.
- [x] Implement scrub, jump, and clip-boundary handling on the master event timeline.
- [x] Add long-press multi-select on event thumbnails with a header delete action.
- [x] Add a header delete action to the event player with confirmation and index redirect.
- [x] Load telemetry sidecars in the player and show speed plus driver-assist indicators during playback.
- [x] Preserve full playback stage height by moving telemetry into stage-safe corner overlays.
- [x] Add a steering-wheel autopilot indicator with white/blue active states backed by `sentrymanager.json` event metadata.
- [x] Reserve a brake-indicator slot in the left stage-safe overlay and show it when brake-applied telemetry is active.
- [x] Show event-level `fsdOnPercent` in the right stage-safe overlay during playback.
- [x] Overlay a transparent 3x3 camera icon grid on the top-left of the main player image.
- [x] Replace the old camera selector row with overlay-driven 1/2/3 camera layouts and camera-target arrows.
- [ ] Add export controls to the event player for starting an export from the current edit state.
- [ ] Surface export readiness, active-job state, and the latest output/error details in the event player UI.
- [ ] Surface timeline coverage gaps when one or more camera angles are missing.

## Phase 4: Editing Model

- [x] Add start/end trim marker UX shell with draggable handles, default range fill, and minimum-gap constraints.
- [x] Add camera marker UX with per-marker layout/camera popup controls on the edit lane.
- [x] Apply camera marker layout/camera selections live when playback crosses each marker.
- [x] Add start-marker layout/camera selection so playback can begin in a saved perspective before the first camera marker.
- [x] Persist player trim and camera markers in each event's `sentrymanager.json` and hydrate them on reload.
- [x] Open the player at the saved trim start when a persisted start marker is present.
- [ ] Normalize the saved trim range, start-marker view, and camera markers into contiguous edit segments.
- [ ] Show derived segment boundaries and active-segment selection on the event timeline.
- [ ] Let users split, merge, and retime segments without rebuilding raw marker state by hand.
- [ ] Add per-segment editing controls for labels, notes, and optional playback-rate overrides.

## Phase 5: Export Pipeline

- [ ] Make export composition match the browser stage rendering for trims, camera switches, multi-camera layouts, and stage-safe overlays.
- [ ] Convert normalized edit segments into an `ffmpeg` render plan.
- [ ] Generate background-rendered telemetry corner overlay assets that can be stitched into the final export timeline.
- [ ] Composite telemetry corner overlays with the source-camera layout render so exported video preserves the viewer telemetry treatment.
- [ ] Render export jobs directly from original source clips.
- [ ] Add export progress reporting and output file management.
- [ ] Handle partial-footage edge cases without invalidating the full export.

## Phase 6: Operational Hardening

- [x] Split page-specific JavaScript so the index and player only load their own modules plus shared helpers.
- [x] Split player-side JavaScript into entry, event, viewer-delete, and media helper modules.
- [x] Split page-specific CSS so the index and player only load their own styles on top of shared base styles.
- [ ] Add structured logging for discovery, telemetry extraction, editing, and export jobs.
- [ ] Add automated tests for discovery, playlist building, telemetry decoding, timeline normalization, and render-plan generation.
- [ ] Add health checks and failure reporting for stack deployment.
- [ ] Document backup, retention, and storage expectations for footage, telemetry artifacts, and rendered exports.
