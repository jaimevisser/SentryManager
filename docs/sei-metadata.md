# Tesla Dashcam SEI Metadata Overview

This note summarizes what Tesla's official dashcam tooling says can be extracted from supported MP4 files, and how that applies to the footage in this repository.

## Bottom Line

Tesla's official [dashcam](https://github.com/teslamotors/dashcam) repository confirms that supported dashcam MP4 files can contain embedded SEI metadata with telemetry such as:

- vehicle speed
- steering wheel angle
- gear state
- left and right blinker state
- brake applied state
- autopilot or self-driving state
- latitude and longitude
- heading
- linear acceleration on three axes

This data is not exposed as ordinary MP4 container tags. It is carried inside H.264 SEI NAL units and decoded with Tesla's `dashcam.proto` protobuf schema.

## Availability Constraints

Tesla's upstream README states that SEI metadata is only expected when all of these are true:

- the clip was recorded on Tesla firmware `2025.44.25` or later
- the car is `HW3` or above
- the clip is not a parked case where Tesla omits SEI metadata

The upstream repo explicitly warns that not all Tesla-generated clips contain SEI data.

## Extractable Fields

The upstream `dashcam.proto` defines this `SeiMetadata` message:

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | `uint32` | Schema or payload version marker. |
| `gear_state` | `enum Gear` | Vehicle gear state. |
| `frame_seq_no` | `uint64` | Frame sequence number tied to the telemetry sample. |
| `vehicle_speed_mps` | `float` | Vehicle speed in meters per second. |
| `accelerator_pedal_position` | `float` | Accelerator pedal position. The schema does not document the unit further. |
| `steering_wheel_angle` | `float` | Steering wheel angle. |
| `blinker_on_left` | `bool` | Left blinker active. |
| `blinker_on_right` | `bool` | Right blinker active. |
| `brake_applied` | `bool` | Brake pedal applied. |
| `autopilot_state` | `enum AutopilotState` | Tesla self-driving or driver-assist state. |
| `latitude_deg` | `double` | Latitude in degrees. |
| `longitude_deg` | `double` | Longitude in degrees. |
| `heading_deg` | `double` | Vehicle heading in degrees. |
| `linear_acceleration_mps2_x` | `double` | Linear acceleration, X axis, in meters per second squared. |
| `linear_acceleration_mps2_y` | `double` | Linear acceleration, Y axis, in meters per second squared. |
| `linear_acceleration_mps2_z` | `double` | Linear acceleration, Z axis, in meters per second squared. |

### Enum Values

`Gear`:

- `GEAR_PARK = 0`
- `GEAR_DRIVE = 1`
- `GEAR_REVERSE = 2`
- `GEAR_NEUTRAL = 3`

`AutopilotState`:

- `NONE = 0`
- `SELF_DRIVING = 1`
- `AUTOSTEER = 2`
- `TACC = 3`

## How Tesla Extracts It

Tesla's upstream tools extract telemetry by:

1. Reading the MP4 `mdat` atom directly.
2. Walking H.264 NAL units.
3. Filtering for NAL type `6`, which is SEI.
4. Filtering again for SEI payload type `5`, which is `user data unregistered`.
5. Removing H.264 emulation-prevention bytes.
6. Decoding the remaining payload as the `SeiMetadata` protobuf.

That means the authoritative path is:

- not ordinary MP4 container metadata
- not `event.json`
- not filename parsing
- but H.264 bitstream SEI payload extraction

## Upstream Tools Worth Reusing

The Tesla repo provides three practical extraction surfaces:

### 1. Browser SEI Explorer

- `sei_explorer.html`
- local-only browser workflow
- shows video playback with SEI values beside the current frame
- can export CSV for one file or a ZIP of CSVs for multiple files

### 2. Python CLI Extractor

- `sei_extractor.py`
- command line CSV output
- uses `dashcam.proto` compiled to Python protobuf bindings
- good fit for server-side ingest or batch indexing

### 3. JavaScript MP4 Parser

- `dashcam-mp4.js`
- parses MP4 structure and SEI payloads in-browser
- already separates low-level MP4 parsing from UI rendering
- useful reference if we want a native JS extractor in SentryManager

## What We Confirmed Locally

Using the footage already in this repository:

- [data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-back.mp4](../data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-back.mp4) shows repeated `H.26[45] User Data Unregistered SEI message` entries when inspected with `ffprobe`, and `ffmpeg -v trace` shows H.264 `nal_unit_type: 6(SEI)` packets.
- [data/TeslaCam/SentryClips/2026-03-26_12-10-33/2026-03-26_12-09-59-front.mp4](../data/TeslaCam/SentryClips/2026-03-26_12-10-33/2026-03-26_12-09-59-front.mp4) did not surface the same SEI user-data markers in the quick `ffprobe` frame inspection.

So the current evidence in this repo matches Tesla's warning that SEI is not guaranteed for every clip, and it supports the working assumption that `SavedClips` are more likely than parked `SentryClips` to contain the richer telemetry.

## What Remains Outside SEI

Even when SEI is absent, we can still extract useful metadata from other sources:

- clip filename timestamps
- camera angle from filename suffix
- MP4 creation time, duration, resolution, codec, and frame timing from `ffprobe`
- event-level `event.json` fields such as timestamp, city, street, reason, and estimated coordinates

These sources complement SEI. They do not replace it.

## Practical SentryManager Implications

For compatible clips, SentryManager can eventually ingest and index:

- motion and control state over time
- turn-signal and braking events
- autopilot state transitions
- position and heading traces
- per-frame or per-sample vehicle telemetry aligned to video playback

The best backend path is probably to adapt Tesla's Python extractor logic into our ingest pipeline, then store decoded SEI samples as time-aligned records per clip.

## Recommended Frontend Format

For SentryManager, the best transport and storage format after backend SEI decoding is a compact binary payload delivered as an `ArrayBuffer`.

The recommended flow is:

1. Decode Tesla's SEI protobuf on the backend.
2. Normalize the samples onto clip-relative or event-relative time.
3. Repack the decoded telemetry into a compact columnar binary layout.
4. Send that binary blob to the frontend and read it with JavaScript typed arrays.

This is a better fit than sending raw protobuf messages or large JSON arrays because:

- JavaScript supports `ArrayBuffer`, `DataView`, and typed arrays natively.
- repeated field names and object overhead disappear
- dense time-series telemetry compresses well in columnar form
- the frontend can render telemetry without redoing MP4 parsing or protobuf decoding
- the same stored blob can be reused for playback overlays, markers, analytics, and export logic

The ideal representation is a small header plus typed-array-backed columns for the main signals, for example:

- sample time deltas
- speed
- steering angle
- heading
- latitude and longitude deltas
- acceleration axes
- gear state
- autopilot state
- packed boolean flags for blinkers and brake state

In practice, this means the browser should receive decoded and repacked telemetry, not raw SEI bitstreams.

## Current Sidecar Format

The app now writes one telemetry sidecar file per segment using the segment timestamp basename plus the `-telemetry.sei.bin` suffix.

Examples:

- `2026-03-28_09-11-48-front.mp4` -> `2026-03-28_09-11-48-telemetry.sei.bin`
- `2026-03-28_09-11-48-back.mp4` -> `2026-03-28_09-11-48-telemetry.sei.bin`

These sidecars are generated during clip discovery, not deferred until playback. If a sidecar already exists, the app leaves it in place and skips re-extraction for that segment.

The `front` camera is used as the primary extraction source when it exists. If a segment has no `front` clip, the app falls back to the first available camera clip for that segment. The telemetry payload is stored in the same ArrayBuffer-oriented columnar binary layout that the frontend can consume later without needing a second conversion step.

Each processed event folder also gets a `sentrymanager.json` file. That marker now carries lightweight event-level metadata such as `hasAutopilotActivity`, which lets the player decide whether to render the steering-wheel indicator without rescanning every segment on page load.

If a segment produces no SEI samples, the app does not create a telemetry sidecar for that segment. Instead, it writes a `sentrymanager.json` file containing `{}` into the event folder so it is still clear that the folder has been processed.