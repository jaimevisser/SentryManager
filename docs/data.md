# Data Model Notes

This document defines the current data terms and persisted records used by SentryManager.

## Current Persisted Artifacts

- Each event folder can contain `sentrymanager.json` with processing state, saved edits, normalized edit segments, and latest-render metadata.
- Compatible clips can produce `*-telemetry.sei.bin` sidecars for frontend telemetry playback.
- Render jobs live in the file-backed store under `.sentrymanager/render-jobs/<status>/<job-id>.json`.
- Event export folders can contain the latest `*.render-plan.json`, the latest rendered `*.mp4` output, and in-flight per-segment intermediates.

## Event Processing Marker

The event processing marker is `sentrymanager.json` inside the event folder.

Fields written directly by the app today:

- `hasAutopilotActivity`: boolean
- `hasSteeringAngleData`: boolean
- `eventCategoryLabel`: string or `null`
- `driverAssistDisplay`: object with `label`, `percent`, and `text` when the event has `SELF_DRIVING`, `AUTOSTEER`, or `TACC` samples
- `fsdOnPercent`: legacy compatibility field retained only when the display label is `FSD`
- `playerEdits`: saved player edit payload
- `normalizedEditSegments`: normalized segment list derived from `playerEdits`
- `latestRender`: metadata for the latest successful export

Implementation notes:

- The SEI processing path updates autopilot and steering flags plus `eventCategoryLabel` and `driverAssistDisplay`.
- `driverAssistDisplay` shows `FSD` only when `SELF_DRIVING` is present. If no `SELF_DRIVING` samples exist but `AUTOSTEER` or `TACC` does, it shows `AP` instead.
- The player and render routes also write `playerEdits` and `normalizedEditSegments`.
- Successful renders persist `latestRender` back into the same file.
- Existing unknown keys are preserved when the marker is rewritten.

## Event Summary

`EventSummary` is the in-memory review record shown in the index and event page.

Current fields:

- `name`
- `path`
- `category`
- `category_label`
- `clip_count`
- `cameras`
- `timestamp`
- `day_label`
- `time_label`
- `thumbnail_path`
- `location_label`
- `trigger_offset_seconds`

## Event Clip And Playlist Payload

`EventClip` is the in-memory clip record used to build per-camera playlists.

Current fields:

- `camera_key`
- `camera_label`
- `segment_key`
- `segment_label`
- `file_name`
- `file_path`

The event page serializes playlists to JSON with these fields per clip:

- `segmentKey`
- `segmentLabel`
- `fileName`
- `url`
- `hasTelemetry`
- `telemetryUrl`

The event page payload also includes:

- `defaultViewKey`
- `playlists`
- `eventMarkerTime`
- `initialStartTime`
- `eventFlags.hasAutopilotActivity`
- `eventFlags.hasSteeringAngleData`
- `eventFlags.driverAssistDisplay`
- `savedEdits`
- `normalizedEditSegments`
- `playerEditsSaveUrl`
- `playerRenderUrl`
- `playerDownloadUrl`
- `activeRenderJob`
- `latestRender`

## Player Edits

`playerEdits` is the persisted editing payload stored in `sentrymanager.json`.

Current fields:

- `trimStartTime`: non-negative float, rounded to milliseconds
- `trimEndTime`: non-negative float, rounded to milliseconds
- `exportFormat`: `4k` or `hd`
- `startMarkerView.layout`: `single`, `double`, or `triple`
- `startMarkerView.cameraKey`: one of the supported camera keys
- `cameraMarkers[]`

Each `cameraMarkers[]` entry includes:

- `id`: positive integer unique within the event
- `time`: non-negative float, rounded to milliseconds
- `layout`: `single`, `double`, or `triple`
- `cameraKey`: one of the supported camera keys

## Edit Segment

An edit segment is the normalized export decision derived from `playerEdits`.

Current fields:

- `id`
- `event_id`
- `timeline_start`
- `timeline_end`
- `layout`
- `primary_camera`
- `visible_cameras`
- `export_format`
- `label`
- `notes`
- `playback_rate`

Implementation notes:

- Segments are generated automatically from trim bounds, the saved start marker, and ordered camera markers.
- The current UI does not expose custom labels, notes, or playback rates yet, so new segments default those to `null`, `null`, and `1.0`.

## Media Index

The render pipeline builds a `mediaIndex` from the source clips in an event folder.

Current fields:

- `absolute_file_path`
- `relative_file_path`
- `camera_key`
- `segment_key`
- `clip_start_time`
- `clip_end_time`
- `duration`
- `frame_rate`
- `width`
- `height`
- `codec_name`
- `has_telemetry_sidecar`
- `has_coverage_gap_after`

Implementation notes:

- Clip timing is cumulative per camera playlist, not based on wall-clock filename gaps.
- `has_coverage_gap_after` is derived from wall-clock gaps between source clips for the same camera.

## Export Job

An export job turns edit segments into a renderable output.

Current persisted fields:

- `id`
- `eventId`
- `status`
- `requestedAt`
- `startedAt`
- `finishedAt`
- `outputProfile`
- `playerEdits`
- `outputPath`
- `renderPlanPath`
- `progressMessage`
- `errorMessage`
- `render`

Current implementation notes:

- Jobs are persisted in `.sentrymanager/render-jobs` rather than a database.
- Status values are `queued`, `running`, `succeeded`, `failed`, and `cancelled`.
- Each event keeps only its latest `succeeded` job record; older succeeded job files for that event are pruned when a new success is recorded.
- Failure messages are sanitized before they are surfaced back to the UI.
- The UI receives `statusUrl` and `downloadUrl` as serialized convenience fields.

## Latest Render Metadata

`latestRender` is stored in `sentrymanager.json` after a successful export.

Current fields:

- `status`
- `requestedAt`
- `outputProfile`
- `outputPath`
- `renderPlanPath`
- `segmentCount`
- `downloadFileName`
- `missingCameras`

Implementation notes:

- After a successful render, the pipeline keeps only the newest output `.mp4` and matching `.render-plan.json` in the event `exports/` folder.
- Timestamped per-segment intermediate directories are treated as temporary and are removed after a successful concat.

The fallback metadata rebuilt from the `exports/` directory exposes:

- `status`
- `outputPath`
- `downloadFileName`
- `renderPlanPath`
- `updatedAt`

## Render Plan

The render plan is generated from normalized edit segments against original source clips.

Current top-level fields:

- `eventId`
- `outputProfile`
- `frameSize`
- `frameRate`
- `segments`
- `overlayConfig`
- `outputPath`
- `intermediateDir`
- `renderPlanPath`
- `mediaIndex`

Each render segment includes:

- `segmentId`
- `browserTimelineStart`
- `browserTimelineEnd`
- `renderTimelineStart`
- `renderTimelineEnd`
- `layout`
- `slots`
- `overlay`
- `missingCameras`

Each slot includes:

- `camera`
- `fragments`
- `x`
- `y`
- `width`
- `height`

Each fragment includes:

- `sourceClip`
- `sourceIn`
- `sourceOut`

Current implementation notes:

- Plans are already generated from normalized edit segments.
- Export composition renders from original source clips and keeps double-layout slot widths even where needed for yuv420p compatibility.
- Render segments track both browser timeline bounds and actual render timeline bounds so missing-camera gaps can shorten slot content without breaking the exported sequence.
