# Data Model Notes

This document defines the initial terminology and core records for SentryManager.

## Raw Clip

A raw clip is one source MP4 file from TeslaCam.

Suggested fields:

- `id`
- `event_id`
- `camera`
- `file_path`
- `relative_path`
- `start_time`
- `end_time`
- `duration_seconds`
- `width`
- `height`
- `fps`
- `has_audio`
- `sha256` or other content fingerprint

## Event

An event is the normalized review unit shown in the UI.

Suggested fields:

- `id`
- `source_root`
- `category`
- `display_name`
- `start_time`
- `end_time`
- `duration_seconds`
- `camera_coverage`
- `clip_count`
- `status`

## Proxy Asset

A proxy asset is a low-resolution review video generated from raw clips for one camera angle within one event.

Suggested fields:

- `id`
- `event_id`
- `camera`
- `file_path`
- `codec`
- `width`
- `height`
- `fps`
- `duration_seconds`
- `generated_at`
- `timeline_map_path`

## Proxy Timeline Map

The proxy timeline map links proxy playback positions back to source clips.

Each row should capture:

- `proxy_start_time`
- `proxy_end_time`
- `source_clip_id`
- `source_start_offset`
- `source_end_offset`
- `camera`

## Edit Segment

An edit segment is a user-authored decision over the master event timeline.

Suggested fields:

- `id`
- `event_id`
- `timeline_start`
- `timeline_end`
- `view_mode`
- `primary_camera`
- `included_cameras`
- `label`
- `notes`
- `playback_rate`

## Export Job

An export job turns edit segments into a renderable output.

Suggested fields:

- `id`
- `event_id`
- `status`
- `requested_at`
- `started_at`
- `finished_at`
- `output_path`
- `render_plan_path`
- `error_message`

## Render Plan

The render plan should be generated from edit segments against original source clips.

The plan should define:

- which source clips are needed
- the trim ranges required from each source clip
- the layout or angle choice for each timeline segment
- any overlays or labels to burn into the output
- final output settings
