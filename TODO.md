# TODO

This file tracks remaining delivery work. Implemented behavior belongs in the README and docs.

## Discovery And Ingest

- [ ] Persist normalized event, clip, and telemetry metadata in a local data store.
- [ ] Represent missing-angle coverage explicitly in the normalized event model.

## Review UI

- [ ] Surface timeline coverage gaps when one or more camera angles are missing.

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

- [ ] Add structured logging for discovery, telemetry extraction, editing, and export jobs.
- [ ] Expand automated tests for discovery, playlist building, telemetry decoding, and remaining timeline/export paths.
- [ ] Add health checks and failure reporting for stack deployment.
- [ ] Document backup, retention, and storage expectations for footage, telemetry artifacts, and rendered exports.
