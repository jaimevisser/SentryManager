from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path


SEI_SIDECAR_SUFFIX = "-telemetry.sei.bin"
PROCESSING_MARKER_NAME = "sentrymanager.json"
PRIMARY_CAMERA_KEY = "front"
CAMERA_KEYS = (
    "front",
    "back",
    "left_repeater",
    "right_repeater",
    "left_pillar",
    "right_pillar",
)

FORMAT_MAGIC = b"SEI1"
FORMAT_VERSION = 1
HEADER_STRUCT = struct.Struct("<4sHHIII")

FIELD_VERSION = 0
FIELD_GEAR_STATE = 1
FIELD_FRAME_SEQ_NO = 2
FIELD_VEHICLE_SPEED = 3
FIELD_ACCELERATOR_PEDAL = 4
FIELD_STEERING_WHEEL_ANGLE = 5
FIELD_BLINKER_LEFT = 6
FIELD_BLINKER_RIGHT = 7
FIELD_BRAKE_APPLIED = 8
FIELD_AUTOPILOT_STATE = 9
FIELD_LATITUDE = 10
FIELD_LONGITUDE = 11
FIELD_HEADING = 12
FIELD_ACCEL_X = 13
FIELD_ACCEL_Y = 14
FIELD_ACCEL_Z = 15

COLUMN_DEFINITIONS = (
    ("time_ms", "I"),
    ("presence_bits", "H"),
    ("message_version", "H"),
    ("frame_seq_no", "Q"),
    ("gear_state", "B"),
    ("autopilot_state", "B"),
    ("flags", "B"),
    ("speed_cmps", "H"),
    ("accelerator_centi", "H"),
    ("steering_tenths_deg", "h"),
    ("heading_cdeg", "H"),
    ("latitude_e7", "i"),
    ("longitude_e7", "i"),
    ("accel_x_mmps2", "h"),
    ("accel_y_mmps2", "h"),
    ("accel_z_mmps2", "h"),
)
COLUMN_MASK = (1 << len(COLUMN_DEFINITIONS)) - 1
HEADER_SIZE = ((HEADER_STRUCT.size + (4 * len(COLUMN_DEFINITIONS))) + 7) & ~7


@dataclass(slots=True)
class Mp4Box:
    start: int
    end: int
    size: int


@dataclass(slots=True)
class SeiSample:
    time_ms: int = 0
    presence_bits: int = 0
    message_version: int = 0
    frame_seq_no: int = 0
    gear_state: int = 0
    autopilot_state: int = 0
    flags: int = 0
    speed_cmps: int = 0
    accelerator_centi: int = 0
    steering_tenths_deg: int = 0
    heading_cdeg: int = 0
    latitude_e7: int = 0
    longitude_e7: int = 0
    accel_x_mmps2: int = 0
    accel_y_mmps2: int = 0
    accel_z_mmps2: int = 0


@dataclass(slots=True)
class SegmentTelemetryResult:
    sidecar_path: Path | None = None
    has_autopilot_activity: bool = False
    has_steering_angle_data: bool = False


def get_sei_sidecar_path(clip_file: Path) -> Path:
    return clip_file.with_suffix(SEI_SIDECAR_SUFFIX)


def get_segment_sei_sidecar_path(event_dir: Path, segment_key: str) -> Path:
    return event_dir / f"{segment_key}{SEI_SIDECAR_SUFFIX}"


def get_event_processing_marker_path(event_dir: Path) -> Path:
    return event_dir / PROCESSING_MARKER_NAME


def load_event_json_payload(event_dir: Path) -> dict[str, object] | None:
    event_file = event_dir / "event.json"
    if not event_file.is_file():
        return None

    try:
        payload = json.loads(event_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def extract_event_category_label(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None

    reason = payload.get("reason")
    if not isinstance(reason, str):
        return None

    normalized_reason = reason.strip().lower()
    if not normalized_reason:
        return None

    if normalized_reason.startswith("sentry_"):
        return "Sentry"
    return "Saved"


def ensure_sei_sidecars(clip_files: list[Path]) -> None:
    segments: dict[tuple[Path, str], dict[str, Path]] = {}
    event_autopilot_activity: dict[Path, bool] = {}
    event_steering_angle_data: dict[Path, bool] = {}
    for clip_file in clip_files:
        segment_key, camera_key = split_clip_stem(clip_file.stem)
        if camera_key == "unknown":
            continue
        segment_entry = segments.setdefault((clip_file.parent, segment_key), {})
        segment_entry[camera_key] = clip_file

    for (event_dir, segment_key), camera_files in segments.items():
        try:
            result = ensure_segment_sei_sidecar(event_dir, segment_key, camera_files)
        except (OSError, ValueError, struct.error):
            continue
        event_autopilot_activity[event_dir] = event_autopilot_activity.get(event_dir, False) or result.has_autopilot_activity
        event_steering_angle_data[event_dir] = event_steering_angle_data.get(event_dir, False) or result.has_steering_angle_data

    for event_dir, _ in segments:
        try:
            ensure_event_processing_marker(
                event_dir,
                event_autopilot_activity.get(event_dir, False),
                event_steering_angle_data.get(event_dir, False),
            )
        except OSError:
            continue


def ensure_segment_sei_sidecar(event_dir: Path, segment_key: str, camera_files: dict[str, Path]) -> SegmentTelemetryResult:
    source_clip = camera_files.get(PRIMARY_CAMERA_KEY)
    if source_clip is None:
        source_clip = next(iter(camera_files.values()), None)
    if source_clip is None:
        return SegmentTelemetryResult()

    sidecar_path = get_segment_sei_sidecar_path(event_dir, segment_key)
    payload, has_autopilot_activity, has_steering_angle_data = build_sei_sidecar_payload(source_clip)
    if payload is None:
        if sidecar_path.exists():
            sidecar_path.unlink()
        return SegmentTelemetryResult(
            has_autopilot_activity=has_autopilot_activity,
            has_steering_angle_data=has_steering_angle_data,
        )

    if sidecar_path.exists():
        return SegmentTelemetryResult(
            sidecar_path=sidecar_path,
            has_autopilot_activity=has_autopilot_activity,
            has_steering_angle_data=has_steering_angle_data,
        )

    temp_path = sidecar_path.with_name(f"{sidecar_path.name}.tmp-{os.getpid()}")
    temp_path.write_bytes(payload)
    temp_path.replace(sidecar_path)
    return SegmentTelemetryResult(
        sidecar_path=sidecar_path,
        has_autopilot_activity=has_autopilot_activity,
        has_steering_angle_data=has_steering_angle_data,
    )


def ensure_event_processing_marker(event_dir: Path, has_autopilot_activity: bool, has_steering_angle_data: bool) -> Path:
    marker_path = get_event_processing_marker_path(event_dir)
    event_payload = load_event_json_payload(event_dir)
    event_category_label = extract_event_category_label(event_payload)
    marker_payload = json.dumps(
        {
            "hasAutopilotActivity": has_autopilot_activity,
            "hasSteeringAngleData": has_steering_angle_data,
            "eventCategoryLabel": event_category_label,
        },
        separators=(",", ":"),
    )
    if marker_path.exists():
        try:
            if marker_path.read_text(encoding="utf-8") == marker_payload:
                return marker_path
        except OSError:
            pass

    temp_path = marker_path.with_name(f"{marker_path.name}.tmp-{os.getpid()}")
    temp_path.write_text(marker_payload, encoding="utf-8")
    temp_path.replace(marker_path)
    return marker_path


def build_sei_sidecar_payload(clip_file: Path) -> tuple[bytes | None, bool, bool]:
    clip_bytes = clip_file.read_bytes()
    samples = extract_sei_samples(clip_bytes)
    has_autopilot_activity = any(
        (sample.presence_bits & (1 << FIELD_AUTOPILOT_STATE)) and sample.autopilot_state != 0
        for sample in samples
    )
    has_steering_angle_data = any(sample.presence_bits & (1 << FIELD_STEERING_WHEEL_ANGLE) for sample in samples)
    if not samples:
        return None, has_autopilot_activity, has_steering_angle_data
    schema_version = max((sample.message_version for sample in samples), default=0)
    return serialize_sei_samples(samples, schema_version), has_autopilot_activity, has_steering_angle_data


def extract_sei_samples(clip_bytes: bytes) -> list[SeiSample]:
    frame_durations_ms = extract_frame_durations_ms(clip_bytes)
    media_data_box = find_box(clip_bytes, 0, len(clip_bytes), "mdat")

    samples: list[SeiSample] = []
    pending_sample: SeiSample | None = None
    frame_index = 0
    elapsed_ms = 0.0
    cursor = media_data_box.start

    while cursor + 4 <= media_data_box.end:
        nal_size = read_u32_be(clip_bytes, cursor)
        cursor += 4
        if nal_size < 1 or cursor + nal_size > len(clip_bytes):
            break

        nal = clip_bytes[cursor: cursor + nal_size]
        nal_type = nal[0] & 0x1F

        if nal_type == 6:
            decoded = decode_sei_nal(nal)
            if decoded is not None:
                pending_sample = decoded
        elif nal_type in (1, 5):
            if pending_sample is not None:
                pending_sample.time_ms = int(round(elapsed_ms))
                samples.append(pending_sample)
                pending_sample = None

            if frame_index < len(frame_durations_ms):
                elapsed_ms += frame_durations_ms[frame_index]
            frame_index += 1

        cursor += nal_size

    return samples


def extract_frame_durations_ms(clip_bytes: bytes) -> list[float]:
    movie_box = find_box(clip_bytes, 0, len(clip_bytes), "moov")
    track_box = find_box(clip_bytes, movie_box.start, movie_box.end, "trak")
    media_box = find_box(clip_bytes, track_box.start, track_box.end, "mdia")
    media_header_box = find_box(clip_bytes, media_box.start, media_box.end, "mdhd")
    media_info_box = find_box(clip_bytes, media_box.start, media_box.end, "minf")
    sample_table_box = find_box(clip_bytes, media_info_box.start, media_info_box.end, "stbl")
    time_to_sample_box = find_box(clip_bytes, sample_table_box.start, sample_table_box.end, "stts")

    media_header_version = clip_bytes[media_header_box.start]
    if media_header_version == 1:
        timescale = read_u32_be(clip_bytes, media_header_box.start + 20)
    else:
        timescale = read_u32_be(clip_bytes, media_header_box.start + 12)

    entry_count = read_u32_be(clip_bytes, time_to_sample_box.start + 4)
    durations_ms: list[float] = []
    cursor = time_to_sample_box.start + 8
    for _ in range(entry_count):
        sample_count = read_u32_be(clip_bytes, cursor)
        sample_delta = read_u32_be(clip_bytes, cursor + 4)
        duration_ms = (sample_delta / timescale) * 1000
        durations_ms.extend(duration_ms for _ in range(sample_count))
        cursor += 8

    return durations_ms


def decode_sei_nal(nal: bytes) -> SeiSample | None:
    if len(nal) < 4:
        return None

    marker_index = 3
    while marker_index < len(nal) and nal[marker_index] == 0x42:
        marker_index += 1

    if marker_index <= 3 or marker_index + 1 >= len(nal) or nal[marker_index] != 0x69:
        return None

    payload = strip_emulation_prevention_bytes(nal[marker_index + 1: -1])
    sample = decode_sei_payload(payload)
    if sample.presence_bits == 0:
        return None
    return sample


def decode_sei_payload(payload: bytes) -> SeiSample:
    sample = SeiSample()
    cursor = 0
    payload_length = len(payload)

    while cursor < payload_length:
        key, cursor = read_varint(payload, cursor)
        field_number = key >> 3
        wire_type = key & 0x07

        if field_number == 1 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            sample.message_version = clamp_u16(value)
            sample.presence_bits |= 1 << FIELD_VERSION
        elif field_number == 2 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            sample.gear_state = clamp_u8(value)
            sample.presence_bits |= 1 << FIELD_GEAR_STATE
        elif field_number == 3 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            sample.frame_seq_no = clamp_u64(value)
            sample.presence_bits |= 1 << FIELD_FRAME_SEQ_NO
        elif field_number == 4 and wire_type == 5:
            value = read_f32_le(payload, cursor)
            cursor += 4
            sample.speed_cmps = clamp_u16(round(value * 100))
            sample.presence_bits |= 1 << FIELD_VEHICLE_SPEED
        elif field_number == 5 and wire_type == 5:
            value = read_f32_le(payload, cursor)
            cursor += 4
            sample.accelerator_centi = clamp_u16(round(value * 100))
            sample.presence_bits |= 1 << FIELD_ACCELERATOR_PEDAL
        elif field_number == 6 and wire_type == 5:
            value = read_f32_le(payload, cursor)
            cursor += 4
            sample.steering_tenths_deg = clamp_i16(round(value * 10))
            sample.presence_bits |= 1 << FIELD_STEERING_WHEEL_ANGLE
        elif field_number == 7 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            if value:
                sample.flags |= 0x01
            sample.presence_bits |= 1 << FIELD_BLINKER_LEFT
        elif field_number == 8 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            if value:
                sample.flags |= 0x02
            sample.presence_bits |= 1 << FIELD_BLINKER_RIGHT
        elif field_number == 9 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            if value:
                sample.flags |= 0x04
            sample.presence_bits |= 1 << FIELD_BRAKE_APPLIED
        elif field_number == 10 and wire_type == 0:
            value, cursor = read_varint(payload, cursor)
            sample.autopilot_state = clamp_u8(value)
            sample.presence_bits |= 1 << FIELD_AUTOPILOT_STATE
        elif field_number == 11 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.latitude_e7 = clamp_i32(round(value * 10_000_000))
            sample.presence_bits |= 1 << FIELD_LATITUDE
        elif field_number == 12 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.longitude_e7 = clamp_i32(round(value * 10_000_000))
            sample.presence_bits |= 1 << FIELD_LONGITUDE
        elif field_number == 13 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.heading_cdeg = clamp_u16(round(value * 100))
            sample.presence_bits |= 1 << FIELD_HEADING
        elif field_number == 14 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.accel_x_mmps2 = clamp_i16(round(value * 1000))
            sample.presence_bits |= 1 << FIELD_ACCEL_X
        elif field_number == 15 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.accel_y_mmps2 = clamp_i16(round(value * 1000))
            sample.presence_bits |= 1 << FIELD_ACCEL_Y
        elif field_number == 16 and wire_type == 1:
            value = read_f64_le(payload, cursor)
            cursor += 8
            sample.accel_z_mmps2 = clamp_i16(round(value * 1000))
            sample.presence_bits |= 1 << FIELD_ACCEL_Z
        else:
            cursor = skip_unknown_field(payload, cursor, wire_type)

    return sample


def serialize_sei_samples(samples: list[SeiSample], schema_version: int) -> bytes:
    column_values = {
        "time_ms": [sample.time_ms for sample in samples],
        "presence_bits": [sample.presence_bits for sample in samples],
        "message_version": [sample.message_version for sample in samples],
        "frame_seq_no": [sample.frame_seq_no for sample in samples],
        "gear_state": [sample.gear_state for sample in samples],
        "autopilot_state": [sample.autopilot_state for sample in samples],
        "flags": [sample.flags for sample in samples],
        "speed_cmps": [sample.speed_cmps for sample in samples],
        "accelerator_centi": [sample.accelerator_centi for sample in samples],
        "steering_tenths_deg": [sample.steering_tenths_deg for sample in samples],
        "heading_cdeg": [sample.heading_cdeg for sample in samples],
        "latitude_e7": [sample.latitude_e7 for sample in samples],
        "longitude_e7": [sample.longitude_e7 for sample in samples],
        "accel_x_mmps2": [sample.accel_x_mmps2 for sample in samples],
        "accel_y_mmps2": [sample.accel_y_mmps2 for sample in samples],
        "accel_z_mmps2": [sample.accel_z_mmps2 for sample in samples],
    }

    offsets: list[int] = []
    column_payloads: list[tuple[int, bytes]] = []
    current_offset = HEADER_SIZE

    for column_name, format_char in COLUMN_DEFINITIONS:
        values = column_values[column_name]
        if not values:
            offsets.append(0)
            continue

        current_offset = align_up(current_offset, 8)
        payload = pack_column(format_char, values)
        offsets.append(current_offset)
        column_payloads.append((current_offset, payload))
        current_offset += len(payload)

    payload = bytearray(current_offset)
    HEADER_STRUCT.pack_into(
        payload,
        0,
        FORMAT_MAGIC,
        FORMAT_VERSION,
        HEADER_SIZE,
        len(samples),
        schema_version,
        COLUMN_MASK,
    )
    if offsets:
        struct.pack_into(f"<{len(offsets)}I", payload, HEADER_STRUCT.size, *offsets)

    for offset, column_payload in column_payloads:
        payload[offset: offset + len(column_payload)] = column_payload

    return bytes(payload)


def find_box(buffer: bytes, start: int, end: int, name: str) -> Mp4Box:
    position = start
    while position + 8 <= end:
        size_32 = read_u32_be(buffer, position)
        box_type = buffer[position + 4: position + 8].decode("ascii", errors="ignore")
        header_size = 16 if size_32 == 1 else 8

        if size_32 == 1:
            size = read_u64_be(buffer, position + 8)
        elif size_32 == 0:
            size = end - position
        else:
            size = size_32

        if size < header_size:
            raise ValueError(f"Invalid MP4 box size for {box_type}")

        if box_type == name:
            return Mp4Box(position + header_size, position + size, size - header_size)

        position += size

    raise ValueError(f'MP4 box "{name}" not found')


def strip_emulation_prevention_bytes(data: bytes) -> bytes:
    stripped = bytearray()
    zero_count = 0
    for byte in data:
        if zero_count >= 2 and byte == 0x03:
            zero_count = 0
            continue
        stripped.append(byte)
        zero_count = 0 if byte != 0 else zero_count + 1
    return bytes(stripped)


def skip_unknown_field(payload: bytes, cursor: int, wire_type: int) -> int:
    if wire_type == 0:
        _, cursor = read_varint(payload, cursor)
        return cursor
    if wire_type == 1:
        return cursor + 8
    if wire_type == 2:
        length, cursor = read_varint(payload, cursor)
        return cursor + length
    if wire_type == 5:
        return cursor + 4
    raise ValueError(f"Unsupported protobuf wire type: {wire_type}")


def read_varint(payload: bytes, cursor: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while cursor < len(payload):
        byte = payload[cursor]
        cursor += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, cursor
        shift += 7
    raise ValueError("Truncated protobuf varint")


def pack_column(format_char: str, values: list[int]) -> bytes:
    if not values:
        return b""
    return struct.pack(f"<{len(values)}{format_char}", *values)


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def read_u32_be(buffer: bytes, offset: int) -> int:
    return struct.unpack_from(">I", buffer, offset)[0]


def read_u64_be(buffer: bytes, offset: int) -> int:
    return struct.unpack_from(">Q", buffer, offset)[0]


def read_f32_le(buffer: bytes, offset: int) -> float:
    return struct.unpack_from("<f", buffer, offset)[0]


def read_f64_le(buffer: bytes, offset: int) -> float:
    return struct.unpack_from("<d", buffer, offset)[0]


def clamp_u8(value: int) -> int:
    return max(0, min(255, int(value)))


def clamp_u16(value: int) -> int:
    return max(0, min(65535, int(value)))


def clamp_i16(value: int) -> int:
    return max(-32768, min(32767, int(value)))


def clamp_i32(value: int) -> int:
    return max(-(2**31), min((2**31) - 1, int(value)))


def clamp_u64(value: int) -> int:
    return max(0, min((2**64) - 1, int(value)))


def split_clip_stem(stem: str) -> tuple[str, str]:
    normalized_stem = stem.lower()
    for camera_key in CAMERA_KEYS:
        suffix = f"-{camera_key}"
        if normalized_stem.endswith(suffix):
            return normalized_stem[: -len(suffix)], camera_key
    return normalized_stem, "unknown"