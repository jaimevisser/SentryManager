# TODO

This file tracks remaining delivery work. Implemented behavior belongs in the README and docs.

## Discovery And Ingest

- [ ] Persist normalized event, clip, and telemetry metadata in a local data store.
- [ ] Represent missing-angle coverage explicitly in the normalized event model.

## Review UI

- [ ] Surface timeline coverage gaps when one or more camera angles are missing.
- [ ] Surface event-indexing progress or pending state in the viewer so save/export actions do not fail opaquely while background indexing is still running.

## Editing Model

- [ ] Show derived segment boundaries and active-segment selection on the event timeline.
- [ ] Let users split, merge, and retime segments without rebuilding raw marker state by hand.
- [ ] Add per-segment editing controls for labels, notes, and optional playback-rate overrides.

## Export Pipeline

- [ ] Finish browser/export parity for trims, camera switches, multi-camera layouts, and stage-safe overlays.
- [ ] Generate background-rendered telemetry corner overlay assets that can be stitched into the final export timeline.
- [ ] Composite telemetry corner overlays with the source-camera layout render so exported video preserves the viewer telemetry treatment.
- [ ] Add export progress reporting and output file management.
- [ ] Handle partial-footage edge cases without invalidating the full export.

## Operational Hardening

- [ ] Continue splitting the remaining oversized renderer and telemetry modules so composition roots stay reviewable and testable.
- [ ] Add structured logging for discovery, telemetry extraction, editing, and export jobs.
- [ ] Audit the player-route load path for other avoidable per-load preprocessing beyond SEI sidecar reuse.
- [ ] Decide whether to ship an optional dedicated-worker compose override for heavier render workloads on top of the new single-container default.
- [ ] Expand automated tests for discovery, playlist building, telemetry decoding, and remaining timeline/export paths.
- [ ] Add health checks and failure reporting for stack deployment.
- [ ] Document backup, retention, and storage expectations for footage and telemetry artifacts.
