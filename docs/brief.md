# SentryManager Product Brief

## Summary

SentryManager turns fragmented TeslaCam and Sentry Mode footage into one reviewable event timeline and a final exported video.

## Primary User Goal

Review one event without manually opening dozens of short clips, then define which camera view or layout should appear over time in the final export.

- start and end points
- camera or layout choice
- final exported sequence

## Core Workflow

1. Mount or point the app at a TeslaCam footage directory.
2. Discover footage and group it into event timelines.
3. Open one event and scrub through synchronized footage.
4. Mark timeline ranges and choose the camera view for each range.
5. Export the result as one rendered video from the original clips.

## Product Principles

- Optimize for review speed over media-player completeness.
- Abstract away the many short source fragments into one event timeline.
- Keep timeline decisions deterministic so export output matches what the user selected.
- Degrade gracefully when footage is missing for one or more angles.

## Scope Notes

- Current implemented behavior lives in [README.md](../README.md).
- Current persisted records and payload shapes live in [docs/data.md](data.md).
- Remaining delivery work lives in [TODO.md](../TODO.md).

This brief stays focused on product direction and constraints.

## Planned Additions

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
