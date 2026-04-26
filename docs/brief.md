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
3. Build per-angle proxy videos for fast review.
4. Open one event and scrub through synchronized footage.
5. Mark timeline ranges and choose the camera view for each range.
6. Export the result as one rendered video from the original clips.

## Product Principles

- Optimize for review speed over media-player completeness.
- Abstract away the many short source fragments into one event timeline.
- Keep timeline decisions deterministic so export output matches what the user selected.
- Treat proxies as disposable editing assets and original clips as canonical source media.
- Degrade gracefully when footage is missing for one or more angles.

## Early UI Shape

The application should eventually provide:

- an event browser
- an event detail page with angle playback and timeline scrubbing
- a segment editor for choosing angles or layouts over time
- an export queue or export detail page

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
