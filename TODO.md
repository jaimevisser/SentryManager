# TODO

This file tracks remaining delivery work. Implemented behavior belongs in the README and docs.

## Discovery And Ingest

- [ ] Persist normalized event, clip, and telemetry metadata in a local data store.
- [ ] Represent missing-angle coverage explicitly in the normalized event model.

## Review UI

- [ ] Surface timeline coverage gaps when one or more camera angles are missing.
- [ ] Surface event-indexing progress or pending state in the viewer so save/export actions do not fail opaquely while background indexing is still running.
- [ ] Add an uncombine flow for metadata-only combined Saved clips.

## Editing Model

- [ ] Show derived segment boundaries and active-segment selection on the event timeline.
- [ ] Let users split, merge, and retime segments without rebuilding raw marker state by hand.
- [ ] Add per-segment editing controls for labels and optional playback-rate overrides.

## Export Pipeline

- [ ] Add browser/export parity regressions for remaining trim-driven view-state and overlay edge cases.
- [ ] Add an export-frame regression that proves top-left date/time advances with timeline offset instead of remaining fixed at event start.
- [ ] Generate background-rendered telemetry corner overlay assets that can be stitched into the final export timeline.
- [ ] Composite telemetry corner overlays with the source-camera layout render so exported video preserves the viewer telemetry treatment.
- [ ] Add export progress reporting and output file management.
- [ ] Handle partial-footage edge cases without invalidating the full export.

## Operational Hardening

- [ ] Continue splitting the remaining oversized renderer and telemetry modules so composition roots stay reviewable and testable.
- [ ] Decide whether a combined owner's `sentrymanager.json` should store owner-local driver-assist durations or the same owner-plus-members aggregate that the viewer/export use today.
- [ ] Extend processing-marker freshness checks to catch non-zero duration drift against existing telemetry sidecars, not just zeroed summaries.
- [ ] Add structured logging for discovery, telemetry extraction, editing, and export jobs.
- [ ] Decide whether to ship an optional dedicated-worker compose override for heavier render workloads on top of the new single-container default.
- [ ] Expand automated tests for remaining discovery, telemetry decoding, and timeline/export paths beyond the covered combined-duration and combined-driver-assist regressions.
- [ ] Add health checks and failure reporting for stack deployment.
- [ ] Document backup, retention, and storage expectations for footage and telemetry artifacts.
