# TODO

## Agent handoff

- The repo currently contains an initial Flask scaffold with Jinja templates, plain JS, Docker, Compose, README, data notes, and adapted AGENTS guidance.
- Compose publishes the app on host port `8765` and mounts TeslaCam footage into the container at `/data/TeslaCam`.
- The starter homepage only performs shallow folder discovery; no real TeslaCam normalization, proxy generation, or export pipeline exists yet.
- The best next implementation slice is Phase 2: build reliable TeslaCam discovery plus `ffprobe`-backed metadata extraction before adding more UI.

This file tracks the delivery plan for SentryManager as discrete implementation steps.

## Phase 1: Foundation

- [x] Create the initial Flask app structure with Jinja templates and static assets.
- [x] Add Docker and Compose files with a mounted TeslaCam footage volume.
- [x] Write the core project documentation and agent guidance.
- [ ] Add basic application configuration management for local, test, and production environments.

## Phase 2: Footage Discovery

- [ ] Implement TeslaCam directory scanning for `SavedClips`, `SentryClips`, and compatible folder layouts.
- [ ] Extract clip metadata with `ffprobe`.
- [ ] Normalize source clips into event records and angle-specific clip sequences.
- [ ] Persist the normalized event and clip metadata in a local data store.

## Phase 3: Proxy Pipeline

- [ ] Define the proxy-generation job model.
- [ ] Stitch source fragments into one low-resolution proxy video per angle per event.
- [ ] Generate proxy timeline maps that relate proxy time ranges back to source clips.
- [ ] Add status tracking for missing clips, partial coverage, and proxy build failures.

## Phase 4: Review UI

- [ ] Build an event browser that lists detected TeslaCam sessions.
- [ ] Add a review page with synchronized angle playback.
- [ ] Implement scrub, jump, and clip-boundary handling on the master event timeline.
- [ ] Surface timeline coverage gaps when one or more camera angles are missing.

## Phase 5: Editing Model

- [ ] Create the edit decision list structure for timeline segments.
- [ ] Let users mark in and out points on the event timeline.
- [ ] Let users choose one camera or a multi-camera layout per segment.
- [ ] Add editing controls for labels, notes, and optional playback-speed changes.

## Phase 6: Export Pipeline

- [ ] Convert edit decisions into an `ffmpeg` render plan.
- [ ] Render export jobs from original source clips rather than proxies.
- [ ] Add export progress reporting and output file management.
- [ ] Handle partial-footage edge cases without invalidating the full export.

## Phase 7: Operational Hardening

- [ ] Add structured logging around ingest, proxy, and export jobs.
- [ ] Add automated tests for directory parsing, timeline normalization, and render-plan generation.
- [ ] Add health checks and failure reporting for stack deployment.
- [ ] Document backup, retention, and storage expectations for footage and rendered exports.
