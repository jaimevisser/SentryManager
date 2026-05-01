# Tesla Dashcam SEI Metadata Overview

This note summarizes what Tesla's upstream dashcam tooling exposes, what we confirmed locally, and how SentryManager currently uses that data.

## Bottom Line

Tesla's official [dashcam](https://github.com/teslamotors/dashcam) repository confirms that supported MP4 clips can carry telemetry in H.264 SEI NAL units.

Useful fields include:

- vehicle speed
- steering wheel angle
- gear state
- left and right blinkers
- brake applied
- autopilot state
- latitude and longitude
- heading
- linear acceleration on three axes

This is not ordinary MP4 container metadata. Tesla stores it in H.264 SEI user-data payloads decoded with the `dashcam.proto` protobuf schema.

## Availability Constraints

Tesla's upstream README says SEI metadata is only expected when all of these are true:

- the clip was recorded on Tesla firmware `2025.44.25` or later
- the car is `HW3` or above
- the clip is not a parked case where Tesla omits SEI metadata

Not every Tesla-generated clip contains SEI data.

## Extractable Fields

The upstream `SeiMetadata` schema covers:

- `version`
- `gear_state`
- `frame_seq_no`
- `vehicle_speed_mps`
- `accelerator_pedal_position`
- `steering_wheel_angle`
- `blinker_on_left`
- `blinker_on_right`
- `brake_applied`
- `autopilot_state`
- `latitude_deg`
- `longitude_deg`
- `heading_deg`
- `linear_acceleration_mps2_x`
- `linear_acceleration_mps2_y`
- `linear_acceleration_mps2_z`

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

Tesla's upstream path is:

1. Reading the MP4 `mdat` atom directly.
2. Walking H.264 NAL units.
3. Filtering for SEI NAL type `6`.
4. Filtering for `user data unregistered` payloads.
5. Stripping H.264 emulation-prevention bytes.
6. Decoding the remaining payload as protobuf.

So the authoritative source is the H.264 bitstream, not `event.json`, filenames, or MP4 container tags.

## What We Confirmed Locally

Local checks in this repo showed:

- [data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-back.mp4](../data/TeslaCam/SavedClips/2026-03-28_09-12-13/2026-03-28_09-11-48-back.mp4) shows repeated `H.26[45] User Data Unregistered SEI message` entries when inspected with `ffprobe`, and `ffmpeg -v trace` shows H.264 `nal_unit_type: 6(SEI)` packets.
- [data/TeslaCam/SentryClips/2026-03-26_12-10-33/2026-03-26_12-09-59-front.mp4](../data/TeslaCam/SentryClips/2026-03-26_12-10-33/2026-03-26_12-09-59-front.mp4) did not surface the same SEI user-data markers in the quick `ffprobe` frame inspection.

That matches Tesla's warning that SEI is not guaranteed, and it supports the working assumption that `SavedClips` are more likely than parked `SentryClips` to contain richer telemetry.

## Non-SEI Metadata

Even without SEI, the app can still use:

- clip filename timestamps
- camera angle from filename suffix
- MP4 creation time, duration, resolution, codec, and frame timing from `ffprobe`
- event-level `event.json` fields such as timestamp, city, street, reason, and estimated coordinates

These complement SEI. They do not replace it.

## Practical SentryManager Implications

For compatible clips, SentryManager can use SEI for:

- motion and control state over time
- turn-signal and braking events
- autopilot state transitions
- position and heading traces
- per-frame or per-sample vehicle telemetry aligned to video playback

The current implementation already does this extraction in Python and repacks the decoded samples into a frontend-friendly binary sidecar.

## Current SentryManager Implementation

The app currently:

- reads the MP4 bitstream directly
- parses frame timing from `moov/trak/mdia/minf/stbl/stts`
- extracts SEI payloads from `mdat`
- timestamps decoded samples against elapsed frame time
- writes one sidecar per segment as `<segment-key>-telemetry.sei.bin`
- updates `sentrymanager.json` with `hasAutopilotActivity`, `hasSteeringAngleData`, `eventCategoryLabel`, and a mode-aware `driverAssistDisplay`

Important behavior from the codebase:

- Sidecars are generated when the event page loads, not during broad discovery.
- The `front` clip is the preferred source for a segment. If no `front` clip exists, the app falls back to the first available camera for that segment.
- Sidecars are segment-scoped, not camera-scoped, so `2026-03-28_09-11-48-front.mp4` and `...-back.mp4` both map to `2026-03-28_09-11-48-telemetry.sei.bin`.
- The event-level assist label prefers `FSD` only when `SELF_DRIVING` appears. If not, but `AUTOSTEER` or `TACC` appears, the app shows `AP` instead.
- If a segment yields no SEI samples, the sidecar is removed or omitted, but the event marker is still written.
- Existing unknown keys in `sentrymanager.json` are preserved when SEI processing rewrites the marker.

See [docs/data.md](data.md) for the current persisted marker fields.

## Current Sidecar Format

Each sidecar starts with:

- magic `SEI1`
- format version `1`
- aligned header size
- sample count
- max observed schema version
- column mask
- one offset per column

The current columns are:

- `time_ms`
- `presence_bits`
- `message_version`
- `frame_seq_no`
- `gear_state`
- `autopilot_state`
- `flags`
- `speed_cmps`
- `accelerator_centi`
- `steering_tenths_deg`
- `heading_cdeg`
- `latitude_e7`
- `longitude_e7`
- `accel_x_mmps2`
- `accel_y_mmps2`
- `accel_z_mmps2`

The binary format is columnar and 8-byte aligned. Numeric values are quantized before packing:

- speed to centimeters per second
- accelerator position to centi-units
- steering angle to tenths of a degree
- heading to centidegrees
- latitude and longitude to `1e-7` degrees
- acceleration to millimeters per second squared

Examples:

- `2026-03-28_09-11-48-front.mp4` -> `2026-03-28_09-11-48-telemetry.sei.bin`
- `2026-03-28_09-11-48-back.mp4` -> `2026-03-28_09-11-48-telemetry.sei.bin`

This gives the frontend a compact `ArrayBuffer` payload without requiring browser-side MP4 parsing or protobuf decoding.