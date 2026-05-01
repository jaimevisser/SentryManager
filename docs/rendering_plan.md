# Rendering Plan

## Summary

SentryManager should build final exports as a deterministic backend rendering pipeline, not as an extension of the browser player.

The renderer can run in a second container alongside the main web app so export work stays isolated from request handling.

The browser remains the review and edit surface. The backend owns:

- normalization of saved player edits into canonical timeline segments
- precise media indexing from original source clips
- generation of a declarative render plan
- background execution of render jobs
- export output management and status reporting

This matches the current product direction:

- browser playback is optimized for review speed, not final composition
- timeline decisions must stay deterministic so export output matches what the user selected
- final rendering should use the original clips rather than proxy media

## Goals

- Make export output match the user's timeline decisions exactly.
- Keep the pipeline understandable and operationally simple.
- Use original TeslaCam clips as the rendering source of truth.
- Handle missing or partial footage without invalidating the whole export.
- Make the pipeline testable without requiring a full render for every change.

## Non-Goals

- Realtime browser composition of the final exported layout
- A full non-linear editing engine
- Distributed job infrastructure in the first implementation
- Perfect parity with browser playback heuristics when those heuristics are imprecise

## Canonical Architecture

The rendering pipeline should be built as five layers:

1. Review state capture
2. Timeline normalization
3. Media indexing and source resolution
4. Render plan generation
5. Background render execution

The browser player may continue saving raw marker-oriented state, but the backend should immediately derive a canonical edit model from that state.

## Source Of Truth

The source of truth for export should be:

- original MP4 clips on disk
- `event.json` for event-level metadata and start/trigger information
- timestamped segment filenames for clip placement on the event timeline
- `sentrymanager.json` for canonical user-authored and processing state
- telemetry sidecars generated from SEI metadata when available
- normalized edit segments derived from saved player edits and written back into `sentrymanager.json`

The source of truth for export should not be:

- browser-estimated clip durations
- current DOM layout state
- the active playback position of the review player
- any transient frontend-only interpretation of the edit lane
- duplicate copies of canonical edit state in Mongo or another secondary store

## Canonical Event Clock

The browser timeline and the render timeline should be treated as related but distinct clocks.

The browser timeline may continue using clip timestamps in segment filenames plus `event.json` metadata as its review-oriented approximation of the event clock.

The render timeline should prioritize gapless media continuity over strict fidelity to filename-derived or `event.json`-derived placement.

Rules:

- Use timestamped segment filenames and `event.json` as the browser-review timeline input, not as an unquestioned rendering truth.
- Build a render-time media index from exact probed clip durations and per-camera clip ordering.
- For final rendering, prioritize making source clips connect gaplessly within each camera lane.
- If filename-derived or `event.json`-derived placement conflicts with exact rendered continuity, rendered continuity wins.
- Preserve an explicit mapping between browser timeline time and render timeline time so the renderer can translate saved browser edits onto the render timeline.
- Preserve detected coverage gaps when they are real absences of footage, but do not introduce artificial gaps solely because metadata clocks disagree.

This means the renderer may produce a corrected render timeline that differs slightly from the browser review timeline. That drift is acceptable as long as the renderer applies saved browser edits deterministically through an explicit browser-to-render timeline translation step.

## Editing Contract

The current player already persists enough raw edit intent to support export:

- `trimStartTime`
- `trimEndTime`
- `startMarkerView`
- `cameraMarkers`
- `exportFormat`

That raw state should remain an input format, not the final export model.

The backend should normalize it into contiguous edit segments with deterministic boundaries.

## Normalized Edit Segment Model

Each exportable segment should be represented as a contiguous interval over the master event timeline.

The normalized edit model should continue to store user intent in browser-timeline coordinates, because that is the timeline the review UI exposes and saves today.

Render planning should then translate each normalized browser-timeline segment into one or more render-timeline intervals before source resolution.

Suggested fields:

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

Normalization rules:

- Start with the trimmed event interval.
- Use `startMarkerView` as the active view at `trimStartTime`.
- Sort camera markers by time and stable id.
- Create a new segment each time a camera marker changes the active view.
- Clamp markers outside the trim window.
- Drop zero-length segments.
- Preserve the exact selected layout and camera choice even if footage is missing.

Render-translation rules:

- Treat the saved browser-timeline segment boundaries as the user's editing intent.
- Translate those boundaries onto the render timeline using the media index's continuity mapping.
- Allow the translated render interval to differ slightly from the browser interval when that is required to keep source footage connected gaplessly.
- Preserve deterministic translation so the same browser edits and media index always produce the same render intervals.

This normalized segment list becomes the canonical contract for export, display of derived segment boundaries, and future segment editing UX.

The canonical serialized copy of that normalized state should live in `sentrymanager.json`.

Mongo should not store a second authoritative copy of edit segments or other event-edit state.

## Media Indexing

Export should use a backend media index built from `ffprobe`, not browser metadata heuristics.

Each source clip should record at least:

- absolute file path
- event-relative path
- camera key
- clip start time on the event timeline
- clip end time on the event timeline
- exact duration
- frame rate
- dimensions
- codec information
- telemetry sidecar availability
- whether the clip participates in a detected coverage gap at the event timeline level

The media index should let the exporter answer two questions precisely:

- which source clip or clips cover a requested timeline interval for a camera
- the exact `sourceIn` and `sourceOut` values needed for each clip fragment

## Render Plan

The render plan should be a declarative JSON artifact generated from:

- one event
- one normalized segment list
- one media index
- one output profile

The render plan should be complete enough that job execution does not need to reinterpret timeline logic.

Suggested top-level fields:

- `eventId`
- `outputProfile`
- `frameSize`
- `frameRate`
- `segments`
- `overlayConfig`
- `outputPath`
- `intermediateDir`

Suggested segment fields:

- `segmentId`
- `browserTimelineStart`
- `browserTimelineEnd`
- `renderTimelineStart`
- `renderTimelineEnd`
- `layout`
- `slots`
- `overlay`
- `missingCameras`

Suggested slot fields:

- `camera`
- `fragments`
- `width`
- `height`

Suggested fragment fields:

- `sourceClip`
- `sourceIn`
- `sourceOut`

Example:

```json
{
  "eventId": "SavedClips/2026-03-28_09-12-13",
  "outputProfile": "4k",
  "frameSize": { "width": 3840, "height": 2160 },
  "frameRate": 30,
  "segments": [
    {
      "segmentId": "seg-001",
      "browserTimelineStart": 12.0,
      "browserTimelineEnd": 18.4,
      "renderTimelineStart": 11.82,
      "renderTimelineEnd": 18.22,
      "layout": "triple",
      "slots": [
        {
          "camera": "front",
          "fragments": [
            {
              "sourceClip": "/data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-front.mp4",
              "sourceIn": 4.2,
              "sourceOut": 10.6
            }
          ],
          "width": 1920,
          "height": 1080
        },
        {
          "camera": "left_repeater",
          "fragments": [
            {
              "sourceClip": "/data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-left_repeater.mp4",
              "sourceIn": 4.2,
              "sourceOut": 10.6
            }
          ],
          "width": 1920,
          "height": 1080
        },
        {
          "camera": "right_repeater",
          "fragments": [
            {
              "sourceClip": "/data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-right_repeater.mp4",
              "sourceIn": 4.2,
              "sourceOut": 10.6
            }
          ],
          "width": 1920,
          "height": 1080
        }
      ],
      "overlay": {
        "telemetry": true
      },
      "missingCameras": []
    }
  ]
}
```

Render-plan timing rules:

- The render plan should record both browser-timeline and render-timeline boundaries for each segment.
- A slot may resolve to multiple clip fragments when a translated render interval crosses source clip boundaries.
- For multi-camera layouts, the rendered segment duration should be the longest resolved slot duration so at least one camera lane remains gapless through the full segment.
- Shorter slot coverage within that segment should end in a deterministic black tile rather than stretching, freezing, or altering the chosen layout.
- Job execution should consume the render-timeline fields and resolved fragments directly without recomputing timeline translation.

## Job Model

Exports should run as background jobs, not inside the request that starts them and not inside the Gunicorn web process.

The renderer can run as that separate worker service in a second container.

The first implementation can stay simple:

- Mongo-backed export job collection
- one worker container in Docker Compose
- web app endpoint to enqueue jobs
- polling endpoint for job status and output metadata

Recommended deployment shape:

- one `app` container for Flask and Gunicorn
- one `worker` container for export execution
- one `mongo` container for job state, render metadata, and queue coordination

Mongo is a better fit here than a local file-backed queue because the app and worker will run as separate services and both need reliable access to shared job state.

Suggested Mongo responsibilities:

- store export job documents
- store progress and error state updates
- store output metadata and render-plan paths
- support simple indexes for job status, event id, and requested time

Mongo should not duplicate canonical event-edit state that already lives in `sentrymanager.json`.

Suggested job states:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Suggested job fields:

- `id`
- `event_id`
- `status`
- `requested_at`
- `started_at`
- `finished_at`
- `render_plan_path`
- `output_path`
- `error_message`
- `progress_message`

## Rendering Strategy

The first version should avoid one giant `ffmpeg` filtergraph for the entire export.

Use staged rendering instead:

1. Resolve each segment into exact source clip fragments.
2. Trim and prepare the required inputs for that segment.
3. Compose the selected layout for that segment.
4. Apply telemetry and other overlays for that segment.
5. Concatenate rendered segment outputs into the final file.

This staged approach is easier to debug, easier to test, and easier to recover if one step fails.

## Layout Composition

Layout composition should mirror the review player's visual rules, but the backend should express those rules independently of the DOM.

The renderer should treat the current event viewer as the visual source of truth for slot placement and metadata treatment.

Viewer-derived slot rules:

- Render into a 16:9 black stage.
- Use `object-fit: contain` semantics for each camera tile against a black background.
- In `single` layout, render only the active camera in the main slot.
- In `double` layout, render the active camera in the main right slot and the previous camera in the viewer sequence in the left slot.
- In `triple` layout, render the active camera across the full-width top row and render the previous and next cameras in the bottom-left and bottom-right slots.
- In `triple` layout, the top row occupies twice the height of the bottom row.
- Do not export the interactive 3x3 camera-picker controls; they are viewer UI only.

The current viewer sequence for neighboring cameras is:

- `front`
- `right_pillar`
- `right_repeater`
- `back`
- `left_repeater`
- `left_pillar`

Use `ffmpeg` layout primitives such as:

- `scale`
- `pad`
- `overlay`
- `xstack`
- `concat`

The render plan should explicitly name which cameras occupy which slots for each layout.

Do not infer export layout from whatever the browser happened to show last.

## Telemetry Overlay Strategy

Telemetry should be rendered as its own overlay asset rather than encoded directly into a large layout filtergraph.

The renderer should mirror the current viewer's metadata placement rather than invent a new export-only treatment.

Viewer-derived metadata rules:

- Reserve bottom-left and bottom-right safe-zone overlays outside the visible video image area when letterboxing or pillarboxing creates available space.
- The left safe zone is a vertical four-cell stack for left blinker, heading, brake, and one empty spacer slot.
- The right safe zone is a vertical four-cell stack for right blinker, speed, autopilot state, and `FSD {percent}%` text.
- Speed is rendered in `km/h`.
- Telemetry icons and text use a high-contrast white treatment with drop-shadow styling; the autopilot icon switches to blue when active.
- Export should not include viewer-only controls, timeline markers, or popovers.

Recommended approach:

- generate a transparent overlay video or image sequence for the event timeline from telemetry sidecars
- trim the overlay asset alongside each export segment
- composite the overlay onto the already-built segment layout

This keeps telemetry logic separate from camera-layout logic and makes the overlay reusable for playback markers, analytics, and export.

### Telemetry Rendering Implementation

Telemetry should be rendered in the backend as its own timeline-aligned RGBA overlay, then composited over each rendered segment.

Implementation flow:

1. Read each segment telemetry sidecar and map samples onto the canonical event timeline.
2. Normalize telemetry values into a renderer-friendly event timeline model.
3. For each output frame time, resolve the active telemetry sample for that point on the timeline.
4. Compute the same visible-video rectangle and safe-zone rectangles used by the current viewer layout.
5. Draw telemetry icons and text into a transparent frame that contains only overlay content.
6. Encode the overlay frames into a transparent intermediate asset for the event timeline.
7. Trim that overlay asset alongside each export segment and composite it onto the rendered video segment.

Rendering rules:

- Do telemetry drawing in Python, not in complex `ffmpeg` text and icon expressions.
- Reuse the same icon assets already used by the viewer.
- Reproduce the current viewer text treatment, including `km/h` speed formatting and `FSD {percent}%` text.
- Show only telemetry-driven metadata, not viewer controls or editing chrome.
- Keep overlay rendering deterministic so the same timeline input always produces the same visual output.

Recommended backend drawing stack:

- Python for telemetry decoding and timeline normalization
- Pillow for RGBA text and icon rendering
- `ffmpeg` only for encoding the transparent overlay asset and compositing it with the rendered video

Preferred intermediate representation:

- render RGBA overlay frames at the export frame rate
- encode them as a transparent intermediate overlay asset for the event timeline
- reuse that overlay asset across per-segment export composition

This keeps telemetry rendering understandable in code, makes parity with the current viewer achievable, and avoids mixing telemetry rendering logic into the already-complex camera layout filtergraph.

## Audio Strategy

Audio is out of scope for the first implementation because the current source set is treated as having no usable audio.

Initial recommendation:

- do not model audio in normalized edit segments
- do not include audio fields in the initial render-plan contract
- render silent video outputs only

If audio becomes relevant later, add it as a separate contract revision rather than partially modeling it now.

## Missing Footage Policy

Missing footage should not silently rewrite the user's edit decision.

If a requested camera is unavailable for some or all of a segment:

- preserve the requested layout in the normalized segment model
- record missing cameras in the render plan
- render a deterministic black tile for unavailable slots
- keep the rest of the segment renderable

If one slot in a multi-camera layout resolves to a shorter continuous duration than another, the segment should still render for the longest resolved slot duration and any exhausted slot should fall back to the same deterministic black tile for its remaining interval.

This preserves the contract that export matches the user's timeline decisions even when source coverage is partial.

## Operational Separation

The web app should be responsible for:

- saving raw player edits
- writing canonical normalized edit state to `sentrymanager.json`
- displaying normalized segments and export readiness
- enqueueing export jobs
- showing status, errors, and download links

The worker should be responsible for:

- validating render prerequisites
- reading canonical edit state from `sentrymanager.json`
- generating or loading the render plan
- invoking `ffmpeg`
- writing outputs and progress updates
- reporting success or failure back to the job store

## Code Organization

To keep the review app and rendering worker separate, the codebase should split backend responsibilities under `app/`:

- `app/frontend/` for Flask routes, templates, static assets, and request-time helpers used by the current review UI
- `app/renderer/` for edit normalization, media indexing, telemetry overlay generation, render-plan generation, Mongo job access, and the worker entrypoint

The goal is not to duplicate shared logic, but to separate request/HTML concerns from rendering-pipeline concerns before the worker grows.

## Recommended Build Order

Implementation should happen in this order:

1. Normalize saved player edits into contiguous edit segments.
2. Add tests for timeline normalization.
3. Build precise media indexing with `ffprobe`.
4. Generate declarative render plans from normalized segments.
5. Add tests for render-plan generation without running `ffmpeg`.
6. Add a simple export job store and background worker.
7. Ship single-camera export first.
8. Add multi-camera layout export.
9. Add telemetry overlay rendering.
10. Surface export state and output management in the event player UI.

## Validation Strategy

The rendering pipeline should be testable in layers.

Recommended test slices:

- timeline normalization unit tests
- clip-resolution unit tests against sample event timelines
- render-plan generation tests with golden JSON fixtures
- worker integration tests for simple export jobs
- one or two end-to-end renders against known sample events

The most important rule is to test the declarative render plan before testing the full media render, because that is where correctness and determinism are defined.

## Immediate Next Slice

The best next implementation slice is:

1. Normalize raw player edits into contiguous backend edit segments.
2. Persist the normalized segment model alongside the existing event processing state.
3. Add a render-plan generator that consumes normalized segments and precise clip metadata.
4. Add automated tests for both normalization and render-plan generation.

That gives the project a stable contract between the review UI and final export without taking on the full worker and `ffmpeg` execution path at the same time.