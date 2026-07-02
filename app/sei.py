from __future__ import annotations

import json
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path


SEI_SIDECAR_SUFFIX = "-telemetry.sei.bin"
ROUTE_SVG_SUFFIX = "-route.svg"
EVENT_ROUTE_SVG_NAME = "route-combined.svg"
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

AUTOPILOT_NONE_STATE = 0
AUTOPILOT_SELF_DRIVING_STATE = 1
AUTOPILOT_AUTOSTEER_STATE = 2
AUTOPILOT_TACC_STATE = 3

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
    autopilot_observed_duration_ms: int = 0
    autopilot_active_duration_ms: int = 0
    self_driving_duration_ms: int = 0
    route_points: list[tuple[float, float]] | None = None


def get_sei_sidecar_path(clip_file: Path) -> Path:
    return clip_file.with_suffix(SEI_SIDECAR_SUFFIX)


def get_segment_sei_sidecar_path(event_dir: Path, segment_key: str) -> Path:
    return event_dir / f"{segment_key}{SEI_SIDECAR_SUFFIX}"


def get_segment_route_svg_path(event_dir: Path, segment_key: str) -> Path:
    return event_dir / f"{segment_key}{ROUTE_SVG_SUFFIX}"


def get_event_route_svg_path(event_dir: Path) -> Path:
    return event_dir / EVENT_ROUTE_SVG_NAME


def event_needs_route_backfill(event_dir: Path) -> bool:
    sidecars = list(event_dir.glob(f"*{SEI_SIDECAR_SUFFIX}"))
    if not sidecars:
        return False

    has_any_segment_route = False
    for sidecar in sidecars:
        segment_key = sidecar.name[: -len(SEI_SIDECAR_SUFFIX)]
        segment_route_svg_path = get_segment_route_svg_path(event_dir, segment_key)
        if segment_route_svg_path.is_file():
            has_any_segment_route = True
            continue
        if not segment_route_svg_path.is_file():
            return True

    event_route_svg_path = get_event_route_svg_path(event_dir)
    if has_any_segment_route and not event_route_svg_path.is_file():
        return True

    if event_route_svg_path.is_file() and not route_svg_has_projection_metadata(event_route_svg_path):
        return True

    return False


def route_svg_has_projection_metadata(route_svg_path: Path) -> bool:
    try:
        payload = route_svg_path.read_text(encoding="utf-8")
    except OSError:
        return False

    return (
        'data-route-projection-version="2"' in payload
        and 'data-route-mean-lat="' in payload
        and 'data-route-mean-lon="' in payload
        and 'data-route-cos-lat="' in payload
        and 'data-route-min-x="' in payload
        and 'data-route-min-y="' in payload
        and 'data-route-span="' in payload
    )


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
    event_autopilot_observed_duration_ms: dict[Path, int] = {}
    event_autopilot_active_duration_ms: dict[Path, int] = {}
    event_self_driving_duration_ms: dict[Path, int] = {}
    event_route_points: dict[Path, list[tuple[str, list[tuple[float, float]]]]] = {}
    for clip_file in clip_files:
        segment_key, camera_key = split_clip_stem(clip_file.stem)
        if camera_key == "unknown":
            continue
        segment_entry = segments.setdefault((clip_file.parent, segment_key), {})
        segment_entry[camera_key] = clip_file

    pending_event_dirs: set[Path] = set()
    for event_dir, segment_key in segments:
        marker_exists = get_event_processing_marker_path(event_dir).is_file()
        if (not marker_exists) or event_needs_route_backfill(event_dir):
            pending_event_dirs.add(event_dir)

    for (event_dir, segment_key), camera_files in segments.items():
        if event_dir not in pending_event_dirs:
            continue
        try:
            result = ensure_segment_sei_sidecar(event_dir, segment_key, camera_files)
        except (OSError, ValueError, struct.error):
            continue
        event_autopilot_activity[event_dir] = event_autopilot_activity.get(event_dir, False) or result.has_autopilot_activity
        event_steering_angle_data[event_dir] = event_steering_angle_data.get(event_dir, False) or result.has_steering_angle_data
        event_autopilot_observed_duration_ms[event_dir] = (
            event_autopilot_observed_duration_ms.get(event_dir, 0) + result.autopilot_observed_duration_ms
        )
        event_autopilot_active_duration_ms[event_dir] = (
            event_autopilot_active_duration_ms.get(event_dir, 0) + result.autopilot_active_duration_ms
        )
        event_self_driving_duration_ms[event_dir] = (
            event_self_driving_duration_ms.get(event_dir, 0) + result.self_driving_duration_ms
        )
        if result.route_points:
            event_route_points.setdefault(event_dir, []).append((segment_key, result.route_points))

    for event_dir, segment_points in event_route_points.items():
        flattened_points: list[tuple[float, float]] = []
        for _, route_points in sorted(segment_points, key=lambda item: item[0]):
            for point in route_points:
                if flattened_points and flattened_points[-1] == point:
                    continue
                flattened_points.append(point)

        event_route_svg_path = get_event_route_svg_path(event_dir)
        route_svg = build_route_svg_from_gps_points(flattened_points)
        if route_svg:
            write_text_if_changed(event_route_svg_path, route_svg)
        elif event_route_svg_path.exists():
            event_route_svg_path.unlink()

    for event_dir, _ in segments:
        if event_dir not in pending_event_dirs:
            continue
        try:
            ensure_event_processing_marker(
                event_dir,
                event_autopilot_activity.get(event_dir, False),
                event_steering_angle_data.get(event_dir, False),
                calculate_driver_assist_display(
                    event_autopilot_active_duration_ms.get(event_dir, 0),
                    event_autopilot_observed_duration_ms.get(event_dir, 0),
                    event_self_driving_duration_ms.get(event_dir, 0),
                ),
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
    route_svg_path = get_segment_route_svg_path(event_dir, segment_key)
    (
        payload,
        has_autopilot_activity,
        has_steering_angle_data,
        autopilot_observed_duration_ms,
        autopilot_active_duration_ms,
        self_driving_duration_ms,
        route_svg,
        route_points,
    ) = build_sei_sidecar_payload(source_clip)
    if payload is None:
        if sidecar_path.exists():
            sidecar_path.unlink()
        if route_svg_path.exists():
            route_svg_path.unlink()
        return SegmentTelemetryResult(
            has_autopilot_activity=has_autopilot_activity,
            has_steering_angle_data=has_steering_angle_data,
            autopilot_observed_duration_ms=autopilot_observed_duration_ms,
            autopilot_active_duration_ms=autopilot_active_duration_ms,
            self_driving_duration_ms=self_driving_duration_ms,
            route_points=route_points,
        )

    if not sidecar_path.exists():
        temp_path = sidecar_path.with_name(f"{sidecar_path.name}.tmp-{os.getpid()}")
        temp_path.write_bytes(payload)
        temp_path.replace(sidecar_path)

    if route_svg:
        write_text_if_changed(route_svg_path, route_svg)
    elif route_svg_path.exists():
        route_svg_path.unlink()

    return SegmentTelemetryResult(
        sidecar_path=sidecar_path,
        has_autopilot_activity=has_autopilot_activity,
        has_steering_angle_data=has_steering_angle_data,
        autopilot_observed_duration_ms=autopilot_observed_duration_ms,
        autopilot_active_duration_ms=autopilot_active_duration_ms,
        self_driving_duration_ms=self_driving_duration_ms,
        route_points=route_points,
    )


def ensure_event_processing_marker(
    event_dir: Path,
    has_autopilot_activity: bool,
    has_steering_angle_data: bool,
    driver_assist_display: dict[str, object] | None,
) -> Path:
    marker_path = get_event_processing_marker_path(event_dir)
    event_payload = load_event_json_payload(event_dir)
    event_category_label = extract_event_category_label(event_payload)
    marker_payload_value: dict[str, object] = {}
    if marker_path.exists():
        try:
            existing_payload = json.loads(marker_path.read_text(encoding="utf-8"))
            if isinstance(existing_payload, dict):
                marker_payload_value = existing_payload
        except (OSError, json.JSONDecodeError):
            marker_payload_value = {}

    marker_payload_value["hasAutopilotActivity"] = has_autopilot_activity
    marker_payload_value["hasSteeringAngleData"] = has_steering_angle_data
    marker_payload_value["eventCategoryLabel"] = event_category_label
    if driver_assist_display is not None:
        marker_payload_value["driverAssistDisplay"] = driver_assist_display
        if driver_assist_display.get("label") == "FSD":
            marker_payload_value["fsdOnPercent"] = driver_assist_display.get("percent")
        else:
            marker_payload_value.pop("fsdOnPercent", None)
    else:
        marker_payload_value.pop("driverAssistDisplay", None)
        marker_payload_value.pop("fsdOnPercent", None)
    marker_payload = json.dumps(marker_payload_value, separators=(",", ":"))
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


def build_sei_sidecar_payload(
    clip_file: Path,
) -> tuple[bytes | None, bool, bool, int, int, int, str | None, list[tuple[float, float]]]:
    clip_bytes = clip_file.read_bytes()
    samples, clip_duration_ms = extract_sei_samples(clip_bytes)
    (
        autopilot_observed_duration_ms,
        autopilot_active_duration_ms,
        self_driving_duration_ms,
    ) = calculate_autopilot_durations(samples, clip_duration_ms)
    has_autopilot_activity = autopilot_active_duration_ms > 0
    has_steering_angle_data = any(sample.presence_bits & (1 << FIELD_STEERING_WHEEL_ANGLE) for sample in samples)
    route_points = extract_gps_points(samples)
    route_svg = build_route_svg_from_gps_points(route_points)
    if not samples:
        return None, has_autopilot_activity, has_steering_angle_data, 0, 0, 0, None, route_points
    schema_version = max((sample.message_version for sample in samples), default=0)
    return (
        serialize_sei_samples(samples, schema_version),
        has_autopilot_activity,
        has_steering_angle_data,
        autopilot_observed_duration_ms,
        autopilot_active_duration_ms,
        self_driving_duration_ms,
        route_svg,
        route_points,
    )


def build_route_svg_content(samples: list[SeiSample]) -> str | None:
    gps_points = extract_gps_points(samples)
    return build_route_svg_from_gps_points(gps_points)


def build_route_svg_from_gps_points(gps_points: list[tuple[float, float]]) -> str | None:
    if len(gps_points) < 2:
        return None

    projected_points, projection = project_points(gps_points)
    if len(projected_points) < 2:
        return None

    bounds = calculate_normalization_bounds(projected_points)
    if bounds is None:
        return None

    filtered_points = drop_nearby_points(projected_points)
    if len(filtered_points) < 2:
        return None

    simplified_points = rdp_simplify(filtered_points)
    if len(simplified_points) < 2:
        return None

    normalized_points = normalize_points_with_bounds(simplified_points, bounds)
    if len(normalized_points) < 2:
        return None

    path_d = build_svg_path_d(normalized_points)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet" '
        'data-route-projection-version="2" '
        f'data-route-mean-lat="{format_projection_float(projection["mean_lat"])}" '
        f'data-route-mean-lon="{format_projection_float(projection["mean_lon"])}" '
        f'data-route-cos-lat="{format_projection_float(projection["cos_lat"])}" '
        f'data-route-min-x="{format_projection_float(bounds["min_x"])}" '
        f'data-route-min-y="{format_projection_float(bounds["min_y"])}" '
        f'data-route-span="{format_projection_float(bounds["span"])}">'
        '<path d="'
        + path_d
        + '" fill="none" stroke="#eef8ff" stroke-width="24" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )


def extract_gps_points(samples: list[SeiSample]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    previous: tuple[int, int] | None = None
    for sample in samples:
        if not (sample.presence_bits & (1 << FIELD_LATITUDE)):
            continue
        if not (sample.presence_bits & (1 << FIELD_LONGITUDE)):
            continue
        key = (sample.latitude_e7, sample.longitude_e7)
        if previous == key:
            continue
        previous = key
        points.append((sample.latitude_e7 / 10_000_000, sample.longitude_e7 / 10_000_000))
    return points


def project_points(points: list[tuple[float, float]]) -> tuple[list[tuple[float, float]], dict[str, float]]:
    if not points:
        return [], {"mean_lat": 0.0, "mean_lon": 0.0, "cos_lat": 1.0}

    mean_lat = sum(latitude for latitude, _ in points) / len(points)
    mean_lon = sum(longitude for _, longitude in points) / len(points)
    cos_lat = math.cos(math.radians(mean_lat))
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6

    projected_points = [
        ((longitude - mean_lon) * cos_lat, latitude - mean_lat)
        for latitude, longitude in points
    ]
    return projected_points, {
        "mean_lat": mean_lat,
        "mean_lon": mean_lon,
        "cos_lat": cos_lat,
    }


def calculate_normalization_bounds(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if not points:
        return None

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)

    span_x = max_x - min_x
    span_y = max_y - min_y
    span = max(span_x, span_y)
    if span <= 0:
        return None

    return {
        "min_x": min_x,
        "min_y": min_y,
        "span": span,
    }


def drop_nearby_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    diagonal = math.hypot(max_x - min_x, max_y - min_y)
    min_step = max(diagonal * 0.0008, 1e-7)

    filtered = [points[0]]
    for point in points[1:-1]:
        if math.hypot(point[0] - filtered[-1][0], point[1] - filtered[-1][1]) >= min_step:
            filtered.append(point)
    filtered.append(points[-1])
    return filtered


def rdp_simplify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    diagonal = math.hypot(max_x - min_x, max_y - min_y)
    epsilon = max(diagonal * 0.002, 2e-7)
    return _rdp(points, epsilon)


def _rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points

    start = points[0]
    end = points[-1]
    max_distance = -1.0
    max_index = -1
    for index in range(1, len(points) - 1):
        distance = perpendicular_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            max_index = index

    if max_distance <= epsilon:
        return [start, end]

    left = _rdp(points[: max_index + 1], epsilon)
    right = _rdp(points[max_index:], epsilon)
    return left[:-1] + right


def perpendicular_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    segment_x = end[0] - start[0]
    segment_y = end[1] - start[1]
    segment_length = math.hypot(segment_x, segment_y)
    if segment_length <= 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])

    cross = abs(
        ((point[0] - start[0]) * segment_y)
        - ((point[1] - start[1]) * segment_x)
    )
    return cross / segment_length


def normalize_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    bounds = calculate_normalization_bounds(points)
    if bounds is None:
        return []

    return normalize_points_with_bounds(points, bounds)


def normalize_points_with_bounds(points: list[tuple[float, float]], bounds: dict[str, float]) -> list[tuple[float, float]]:
    min_x = bounds["min_x"]
    min_y = bounds["min_y"]
    span = bounds["span"]

    canvas_size = 1000
    padding = 40
    drawable = canvas_size - (padding * 2)

    normalized: list[tuple[float, float]] = []
    for x, y in points:
        nx = padding + (((x - min_x) / span) * drawable)
        ny = padding + (((y - min_y) / span) * drawable)
        normalized.append((nx, canvas_size - ny))
    return normalized


def build_svg_path_d(points: list[tuple[float, float]]) -> str:
    if len(points) <= 2:
        return build_polyline_path_d(points)

    if len(points) <= 8:
        return build_polyline_path_d(points)

    return build_smoothed_path_d(points)


def build_polyline_path_d(points: list[tuple[float, float]]) -> str:
    return " ".join(
        f"M {format_float(points[0][0])} {format_float(points[0][1])}" if index == 0
        else f"L {format_float(point[0])} {format_float(point[1])}"
        for index, point in enumerate(points)
    )


def build_smoothed_path_d(points: list[tuple[float, float]]) -> str:
    segments = [f"M {format_float(points[0][0])} {format_float(points[0][1])}"]
    for index in range(len(points) - 1):
        p0 = points[index - 1] if index > 0 else points[index]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[index + 2] if index + 2 < len(points) else p2

        c1x = p1[0] + ((p2[0] - p0[0]) / 6)
        c1y = p1[1] + ((p2[1] - p0[1]) / 6)
        c2x = p2[0] - ((p3[0] - p1[0]) / 6)
        c2y = p2[1] - ((p3[1] - p1[1]) / 6)

        segments.append(
            "C "
            f"{format_float(c1x)} {format_float(c1y)} "
            f"{format_float(c2x)} {format_float(c2y)} "
            f"{format_float(p2[0])} {format_float(p2[1])}"
        )
    return " ".join(segments)


def format_float(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def format_projection_float(value: float) -> str:
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def write_text_if_changed(path: Path, content: str) -> None:
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except OSError:
            pass

    temp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def calculate_autopilot_durations(samples: list[SeiSample], clip_duration_ms: int) -> tuple[int, int, int]:
    if not samples or clip_duration_ms <= 0:
        return 0, 0, 0

    observed_duration_ms = 0
    active_duration_ms = 0
    self_driving_duration_ms = 0
    for index, sample in enumerate(samples):
        next_time_ms = clip_duration_ms
        if index + 1 < len(samples):
            next_time_ms = samples[index + 1].time_ms
        interval_duration_ms = max(0, next_time_ms - sample.time_ms)
        if interval_duration_ms == 0:
            continue
        if not (sample.presence_bits & (1 << FIELD_AUTOPILOT_STATE)):
            continue
        observed_duration_ms += interval_duration_ms
        if sample.autopilot_state != AUTOPILOT_NONE_STATE:
            active_duration_ms += interval_duration_ms
        if sample.autopilot_state == AUTOPILOT_SELF_DRIVING_STATE:
            self_driving_duration_ms += interval_duration_ms

    return observed_duration_ms, active_duration_ms, self_driving_duration_ms


def calculate_autopilot_on_percentage(active_duration_ms: int, observed_duration_ms: int) -> float | None:
    if observed_duration_ms <= 0:
        return None
    return round((active_duration_ms / observed_duration_ms) * 100, 2)


def calculate_driver_assist_display(
    active_duration_ms: int,
    observed_duration_ms: int,
    self_driving_duration_ms: int,
) -> dict[str, object] | None:
    if observed_duration_ms <= 0:
        return None

    if self_driving_duration_ms > 0:
        percent = round((self_driving_duration_ms / observed_duration_ms) * 100, 2)
        return {
            "label": "FSD",
            "percent": percent,
            "text": f"FSD {round(percent)}%",
        }

    if active_duration_ms > 0:
        percent = round((active_duration_ms / observed_duration_ms) * 100, 2)
        return {
            "label": "AP",
            "percent": percent,
            "text": f"AP {round(percent)}%",
        }

    return None


def extract_sei_samples(clip_bytes: bytes) -> tuple[list[SeiSample], int]:
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

    return samples, int(round(elapsed_ms))


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