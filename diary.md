# Diary
Add new stuff at the bottom. Keep sections per date. Add times to entries.

## Agent Handoff

- The repo now has a working Flask review app with grouped event browsing, an event player, plain-JS controls, Docker/Compose wiring, typed config loading, and project docs.
- Compose publishes the app on `8765`, mounts TeslaCam footage at `/data/TeslaCam`, and can write telemetry sidecars plus `sentrymanager.json` markers back into event folders.
- Event discovery scans direct event folders plus one- and two-level TeslaCam layouts, caches summaries, and enriches cards from `event.json`, `thumb.png`, and `sentrymanager.json`.
- The review UI supports grouped browsing, thumbnails, location/category chips, trigger-aware Sentry defaults, synchronized clip progression, composite camera views, and telemetry-backed speed, blinker, and autopilot indicators.
- The Flask UI now lives under `app/frontend/`; render normalization and plan generation live under `app/renderer/`.
- Player edits support trim handles, a saved start marker, and camera markers. Saved edits are normalized into contiguous `normalizedEditSegments` in `sentrymanager.json`.
- The renderer probes clips with `ffprobe`, builds declarative plans from normalized segments, and runs queued jobs in the `worker` service via `.sentrymanager/render-jobs`.
- `tests/test_renderer_pipeline.py` covers edit normalization plus render-plan generation across clip boundaries and missing-camera cases without invoking `ffmpeg`.
- The app container now includes `ffmpeg`, and queued export plus latest-download flow was validated end to end against `SavedClips/2026-03-28_09-12-13`.
- Export telemetry now matches the browser more closely: it uses the browser safe-zone geometry, sizes heading arrows from the full safe zone, and uses bundled Tektur plus tracked text and glow for the right-corner speed unit and FSD label.
- A Playwright render-snapshot suite compares deterministic browser frames against export frames for left blinker, right blinker, brake, and blue-FSD fixtures from real `SavedClips` footage; the snapshot hook waits for initial seeks to settle.
- Failed render jobs now store short sanitized summaries instead of raw `ffmpeg` stderr, and the player UI caps long render status strings.
- Double-layout export slots now force even widths, fixing `ffmpeg pad` failures on yuv420p exports that otherwise split the 1920px stage into two 941px columns.
- Added the `tersify` skill under `.github/skills/tersify/`, used it to compact its own prompt after a duplicate-body edit, and tersified `AGENTS.md` without dropping workflow constraints.

### 2026-05-01
- 20:23 Removed completed work from `TODO.md` and moved current functionality notes into `README.md`, `docs/brief.md`, and `docs/data.md`.
- 20:27 Refreshed `docs/data.md` against the code so it documents the real `sentrymanager.json`, `playerEdits`, normalized segments, playlists, media index, render jobs, and render-plan fields.
- 20:36 Tersified `docs/brief.md`, removed duplicated implementation detail, and pointed readers to `README.md`, `docs/data.md`, and `TODO.md` for current state.
- 20:39 Tersified `docs/sei-metadata.md` and updated it with current code-path behavior, including event-page sidecar generation, segment-level sidecar naming, marker updates, and the packed binary column format.
- 20:51 Changed driver-assist percentage display to prefer `FSD` only for `SELF_DRIVING`, fall back to `AP` for `AUTOSTEER` plus `TACC`, and threaded that mode-aware label through both stage and export rendering.