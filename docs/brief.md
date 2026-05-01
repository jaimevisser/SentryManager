# SentryManager Product Brief

## Summary

SentryManager is a TeslaCam review and editing tool focused on turning fragmented multi-angle dashcam and Sentry Mode footage into a usable event timeline.

The product should make it easy to inspect a Tesla event, move through it quickly, decide which camera view matters at each moment, and export a polished single video assembled from the original footage.

## Primary User Goal

The user wants to review a TeslaCam event without manually opening dozens of short camera clips and then define a sequence of timeline segments that specify:

- where the segment starts and ends
- which camera or camera layout should be shown
- what the final exported video should contain

## Core Workflow

1. Mount or point the app at a TeslaCam footage directory.
2. Discover footage and group it into event timelines.
3. Open one event and scrub through synchronized footage.
4. Mark timeline ranges and choose the camera view for each range.
5. Export the result as one rendered video from the original clips.

## Current Implementation

- Event discovery, grouped browsing, and event detail playback are implemented.
- The player supports synchronized single, double, and triple camera layouts plus telemetry-backed speed, blinker, brake, autopilot, and `fsdOnPercent` overlays.
- Saved edits support trim handles, a start marker, and camera markers, then normalize into deterministic edit segments.
- Exports run from original source clips through a worker-backed render pipeline, and browser-versus-export snapshot tests cover real `SavedClips` fixtures.

## Product Principles

- Optimize for review speed over media-player completeness.
- Abstract away the many short source fragments into one event timeline.
- Keep timeline decisions deterministic so export output matches what the user selected.
- Degrade gracefully when footage is missing for one or more angles.

## UI Shape

The application provides:

- an event browser
- an event detail page with angle playback and timeline scrubbing
- trim and camera-marker editing on the event timeline
- export controls with job state in the player

Planned additions:

- richer segment editing for split, merge, retime, labels, notes, and playback-rate overrides
- clearer missing-angle coverage surfacing
- dedicated export progress and output management views

## Non-Goals For The First Iterations

- Full non-linear editing features comparable to professional video software
- Collaborative editing workflows
- Real-time browser rendering of final composited output
- High-precision native playback guarantees inside the browser

## Non-Functional Constraints

- Run inside a Docker-based stack.
- Work from a mounted TeslaCam volume.
- Use a Python backend and server-rendered Jinja templates.
- Use plain JavaScript for frontend behavior.
- Keep the codebase understandable and operationally simple.
