from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import io
import json
from fractions import Fraction
import math
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

from ..sei import COLUMN_DEFINITIONS, EVENT_ROUTE_SVG_NAME, FORMAT_MAGIC, FORMAT_VERSION, HEADER_SIZE


CAMERA_ORDER = (
    "front",
    "back",
    "left_repeater",
    "right_repeater",
    "left_pillar",
    "right_pillar",
)

CAMERA_LAYOUT_SEQUENCE = (
    "front",
    "right_pillar",
    "right_repeater",
    "back",
    "left_repeater",
    "left_pillar",
)

PLAYER_LAYOUT_OPTIONS = {"single", "double", "triple"}
EXPORT_PROFILES = {
    "4k": {"width": 3840, "height": 2160},
    "hd": {"width": 1920, "height": 1080},
}
MISSING_CAMERA_DURATION_TOLERANCE = 0.25
SPEED_PRESENT_MASK = 1 << 3
STEERING_ANGLE_PRESENT_MASK = 1 << 5
BLINKER_LEFT_PRESENT_MASK = 1 << 6
BLINKER_RIGHT_PRESENT_MASK = 1 << 7
BRAKE_PRESENT_MASK = 1 << 8
AUTOPILOT_PRESENT_MASK = 1 << 9
LATITUDE_PRESENT_MASK = 1 << 10
LONGITUDE_PRESENT_MASK = 1 << 11
HEADING_PRESENT_MASK = 1 << 12
AUTOPILOT_NONE_STATE = 0
BLINKER_LEFT_FLAG_MASK = 0x01
BLINKER_RIGHT_FLAG_MASK = 0x02
BRAKE_FLAG_MASK = 0x04
ROUTE_MAP_CANVAS_SIZE = 1000.0
ROUTE_MAP_PADDING = 40.0
ROUTE_DOT_RADIUS_AT_CANVAS = 26.0
ROUTE_DOT_FILL = (255, 51, 45, 255)
ROUTE_DOT_STROKE = (0, 0, 0, 166)
BASE_RENDER_WIDTH = 1920
STAGE_PADDING_AT_BASE_WIDTH = 14.0
DOUBLE_LAYOUT_GAP_AT_BASE_WIDTH = 10.0
FRONTEND_ASSET_ROOT = Path(__file__).resolve().parent.parent / "frontend" / "static"
IMAGE_ASSET_ROOT = FRONTEND_ASSET_ROOT / "images"
FONT_CANDIDATES = (
    str(FRONTEND_ASSET_ROOT / "fonts" / "tektur-latin.woff2"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
MDI_ASSET_ROOT = FRONTEND_ASSET_ROOT / "mdi"
TELEMETRY_COLOR = (246, 251, 255, 255)
TELEMETRY_SHADOW = (0, 0, 0, 160)
AUTOPILOT_ACTIVE_COLOR = (94, 169, 255, 245)
HEADING_LABEL_COLOR = (0, 0, 0, 224)
SVG_ICON_CACHE: dict[tuple[str, int], Image.Image | None] = {}


@dataclass(frozen=True)
class NormalizedSegment:
    id: str
    event_id: str
    timeline_start: float
    timeline_end: float
    layout: str
    primary_camera: str
    visible_cameras: list[str]
    export_format: str
    label: str | None
    notes: str | None
    playback_rate: float


@dataclass(frozen=True)
class MediaClip:
    absolute_file_path: str
    relative_file_path: str
    camera_key: str
    segment_key: str
    clip_start_time: float
    clip_end_time: float
    duration: float
    frame_rate: float
    width: int
    height: int
    codec_name: str
    has_telemetry_sidecar: bool
    has_coverage_gap_after: bool


@dataclass(frozen=True)
class RenderFragment:
    sourceClip: str
    sourceIn: float
    sourceOut: float


@dataclass(frozen=True)
class RenderSlot:
    camera: str
    fragments: list[RenderFragment]
    x: int
    y: int
    width: int
    height: int


def get_normalized_edit_segments(
    event_id: str,
    player_edits: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not isinstance(player_edits, dict):
        return []

    trim_start_time = _coerce_nonnegative_float(player_edits.get("trimStartTime"))
    trim_end_time = _coerce_nonnegative_float(player_edits.get("trimEndTime"))
    start_marker_view = _normalize_view(player_edits.get("startMarkerView"))
    export_format = _normalize_export_format(player_edits.get("exportFormat"))
    raw_markers = player_edits.get("cameraMarkers")
    if trim_start_time is None or trim_end_time is None or trim_end_time <= trim_start_time or start_marker_view is None:
        return []
    if not isinstance(raw_markers, list):
        return []

    markers: list[dict[str, object]] = []
    seen_marker_ids: set[int] = set()
    for raw_marker in raw_markers:
        if not isinstance(raw_marker, dict):
            continue
        marker_id = raw_marker.get("id")
        marker_time = _coerce_nonnegative_float(raw_marker.get("time"))
        marker_view = _normalize_view(raw_marker)
        if not isinstance(marker_id, int) or isinstance(marker_id, bool) or marker_id < 1 or marker_id in seen_marker_ids:
            continue
        if marker_time is None or marker_view is None:
            continue
        seen_marker_ids.add(marker_id)
        markers.append(
            {
                "id": marker_id,
                "time": marker_time,
                "layout": marker_view["layout"],
                "cameraKey": marker_view["cameraKey"],
            }
        )

    markers.sort(key=lambda marker: (float(marker["time"]), int(marker["id"])))

    active_view = {
        "layout": start_marker_view["layout"],
        "cameraKey": start_marker_view["cameraKey"],
    }
    current_start = trim_start_time
    segments: list[NormalizedSegment] = []
    next_segment_index = 1

    for marker in markers:
        marker_time = max(trim_start_time, min(trim_end_time, float(marker["time"])))
        next_view = {
            "layout": str(marker["layout"]),
            "cameraKey": str(marker["cameraKey"]),
        }

        if marker_time <= current_start:
            active_view = next_view
            continue

        if next_view == active_view:
            continue

        segment = _build_segment(
            event_id=event_id,
            segment_index=next_segment_index,
            start_time=current_start,
            end_time=marker_time,
            view=active_view,
            export_format=export_format,
        )
        if segment is not None:
            segments.append(segment)
            next_segment_index += 1
        current_start = marker_time
        active_view = next_view

    final_segment = _build_segment(
        event_id=event_id,
        segment_index=next_segment_index,
        start_time=current_start,
        end_time=trim_end_time,
        view=active_view,
        export_format=export_format,
    )
    if final_segment is not None:
        segments.append(final_segment)

    return [asdict(segment) for segment in segments]


def build_render_plan(
    event_dir: Path,
    footage_root: Path,
    event_id: str,
    player_edits: dict[str, object] | None,
    output_profile: str | None = None,
) -> dict[str, object]:
    normalized_segments = get_normalized_edit_segments(event_id, player_edits)
    if not normalized_segments:
        raise ValueError("No exportable segments were found in the saved player edits.")

    profile_key = _resolve_output_profile(player_edits, output_profile)
    frame_size = EXPORT_PROFILES[profile_key]
    media_index = _build_media_index(event_dir, footage_root)
    if not media_index:
        raise ValueError("No source clips were found for this event.")

    render_segments = _build_render_segments(normalized_segments, frame_size, media_index)
    output_paths = _build_render_output_paths(event_dir, profile_key)
    return {
        "eventId": event_id,
        "outputProfile": profile_key,
        "frameSize": frame_size,
        "frameRate": _pick_render_frame_rate(media_index),
        "segments": render_segments,
        "overlayConfig": {"telemetry": False},
        **output_paths,
        "mediaIndex": [asdict(clip) for clip in media_index],
    }


def _resolve_output_profile(player_edits: dict[str, object] | None, output_profile: str | None) -> str:
    requested_profile = output_profile
    if requested_profile is None and isinstance(player_edits, dict):
        requested_profile = player_edits.get("exportFormat")
    return _normalize_export_format(requested_profile)


def _build_render_segments(
    normalized_segments: list[dict[str, object]],
    frame_size: dict[str, int],
    media_index: list[MediaClip],
) -> list[dict[str, object]]:
    render_segments: list[dict[str, object]] = []
    render_timeline_cursor = 0.0
    for segment in normalized_segments:
        render_segment, segment_duration = _build_render_segment(
            segment=segment,
            frame_size=frame_size,
            media_index=media_index,
            render_timeline_cursor=render_timeline_cursor,
        )
        render_segments.append(render_segment)
        render_timeline_cursor += segment_duration
    return render_segments


def _build_render_segment(
    segment: dict[str, object],
    frame_size: dict[str, int],
    media_index: list[MediaClip],
    render_timeline_cursor: float,
) -> tuple[dict[str, object], float]:
    slots, slot_durations = _build_render_slots(segment, frame_size, media_index)
    segment_duration = max(slot_durations.values(), default=0.0)
    if segment_duration <= 0:
        segment_duration = float(segment["timeline_end"]) - float(segment["timeline_start"])

    render_segment = {
        "segmentId": segment["id"],
        "browserTimelineStart": segment["timeline_start"],
        "browserTimelineEnd": segment["timeline_end"],
        "renderTimelineStart": _round_time(render_timeline_cursor),
        "renderTimelineEnd": _round_time(render_timeline_cursor + segment_duration),
        "layout": segment["layout"],
        "slots": slots,
        "overlay": {"telemetry": any(_slot_has_telemetry(slot) for slot in slots)},
        "missingCameras": _find_missing_cameras(slot_durations, segment_duration),
    }
    return render_segment, segment_duration


def _build_render_slots(
    segment: dict[str, object],
    frame_size: dict[str, int],
    media_index: list[MediaClip],
) -> tuple[list[dict[str, object]], dict[str, float]]:
    slot_specs = _get_layout_slot_specs(
        str(segment["layout"]),
        str(segment["primary_camera"]),
        frame_size["width"],
        frame_size["height"],
    )
    slots: list[dict[str, object]] = []
    slot_durations: dict[str, float] = {}
    for slot_spec in slot_specs:
        fragments = _resolve_fragments(
            media_index=media_index,
            camera_key=slot_spec["camera"],
            timeline_start=float(segment["timeline_start"]),
            timeline_end=float(segment["timeline_end"]),
        )
        slot_durations[slot_spec["camera"]] = sum(fragment.sourceOut - fragment.sourceIn for fragment in fragments)
        slots.append(
            {
                "camera": slot_spec["camera"],
                "fragments": [asdict(fragment) for fragment in fragments],
                "x": slot_spec["x"],
                "y": slot_spec["y"],
                "width": slot_spec["width"],
                "height": slot_spec["height"],
            }
        )
    return slots, slot_durations


def _find_missing_cameras(slot_durations: dict[str, float], segment_duration: float) -> list[str]:
    return sorted(
        camera_key
        for camera_key, slot_duration in slot_durations.items()
        if slot_duration + MISSING_CAMERA_DURATION_TOLERANCE < segment_duration
    )


def _build_render_output_paths(event_dir: Path, profile_key: str) -> dict[str, str]:
    output_dir = event_dir / "exports"
    plan_timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    intermediate_dir = output_dir / f"{plan_timestamp}-{profile_key}-segments"
    output_path = output_dir / f"{event_dir.name}-{profile_key}-{plan_timestamp}.mp4"
    render_plan_path = output_dir / f"{event_dir.name}-{profile_key}-{plan_timestamp}.render-plan.json"
    return {
        "outputPath": str(output_path),
        "intermediateDir": str(intermediate_dir),
        "renderPlanPath": str(render_plan_path),
    }


def render_event(
    event_dir: Path,
    footage_root: Path,
    event_id: str,
    player_edits: dict[str, object] | None,
    output_profile: str | None = None,
) -> dict[str, object]:
    render_plan = build_render_plan(
        event_dir=event_dir,
        footage_root=footage_root,
        event_id=event_id,
        player_edits=player_edits,
        output_profile=output_profile,
    )

    _prepare_render_plan_outputs(render_plan)

    media_clips_by_path = {
        str(clip["absolute_file_path"]): clip
        for clip in render_plan["mediaIndex"]
    }
    event_payload = _load_event_payload(event_dir)
    event_base_timestamp = _get_event_base_timestamp(event_payload, event_dir)
    event_location_label = _get_event_location_label(event_payload)
    event_processing_state = _load_event_processing_state(event_dir)
    event_driver_assist_display = _get_event_driver_assist_display(event_processing_state)

    intermediate_dir = Path(render_plan["intermediateDir"])
    segment_outputs = _render_plan_segments(
        render_plan=render_plan,
        event_dir=event_dir,
        event_driver_assist_display=event_driver_assist_display,
        event_base_timestamp=event_base_timestamp,
        event_location_label=event_location_label,
        media_clips_by_path=media_clips_by_path,
        intermediate_dir=intermediate_dir,
    )

    concat_list = intermediate_dir / "segments.txt"
    concat_list.write_text(
        "".join(f"file {shlex.quote(str(segment_output))}\n" for segment_output in segment_outputs),
        encoding="utf-8",
    )
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(render_plan["outputPath"]),
        ]
    )

    _prune_successful_render_outputs(render_plan)
    return _build_render_result(render_plan)


def _prepare_render_plan_outputs(render_plan: dict[str, object]) -> None:
    output_dir = Path(str(render_plan["outputPath"])).parent
    intermediate_dir = Path(str(render_plan["intermediateDir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    Path(str(render_plan["renderPlanPath"])).write_text(
        json.dumps(render_plan, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _render_plan_segments(
    render_plan: dict[str, object],
    event_dir: Path,
    event_driver_assist_display: dict[str, object] | None,
    event_base_timestamp: datetime | None,
    event_location_label: str | None,
    media_clips_by_path: dict[str, dict[str, object]],
    intermediate_dir: Path,
) -> list[Path]:
    segment_outputs: list[Path] = []
    for segment in render_plan["segments"]:
        segment_output = intermediate_dir / f"{segment['segmentId']}.mp4"
        _render_segment(
            segment=segment,
            event_dir=event_dir,
            event_driver_assist_display=event_driver_assist_display,
            event_base_timestamp=event_base_timestamp,
            event_location_label=event_location_label,
            frame_size=render_plan["frameSize"],
            frame_rate=float(render_plan["frameRate"]),
            media_clips_by_path=media_clips_by_path,
            output_path=segment_output,
        )
        segment_outputs.append(segment_output)
    return segment_outputs


def _build_render_result(render_plan: dict[str, object]) -> dict[str, object]:
    return {
        "status": "succeeded",
        "requestedAt": datetime.now(UTC).isoformat(),
        "outputProfile": render_plan["outputProfile"],
        "outputPath": str(render_plan["outputPath"]),
        "renderPlanPath": str(render_plan["renderPlanPath"]),
        "segmentCount": len(render_plan["segments"]),
        "downloadFileName": Path(str(render_plan["outputPath"])).name,
        "missingCameras": sorted(
            {
                camera
                for segment in render_plan["segments"]
                for camera in segment["missingCameras"]
            }
        ),
    }


def _prune_successful_render_outputs(render_plan: dict[str, object]) -> None:
    output_path = Path(str(render_plan["outputPath"]))
    render_plan_path = Path(str(render_plan["renderPlanPath"]))
    output_dir = output_path.parent

    for candidate in output_dir.glob("*.mp4"):
        if candidate == output_path:
            continue
        try:
            candidate.unlink()
        except OSError:
            continue

    for candidate in output_dir.glob("*.render-plan.json"):
        if candidate == render_plan_path:
            continue
        try:
            candidate.unlink()
        except OSError:
            continue

    for candidate in output_dir.glob("*-segments"):
        if not candidate.is_dir():
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            continue


def get_latest_render_metadata(event_dir: Path) -> dict[str, object] | None:
    output_dir = event_dir / "exports"
    if not output_dir.is_dir():
        return None

    output_files = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not output_files:
        return None

    latest_output = output_files[0]
    render_plan_files = sorted(output_dir.glob("*.render-plan.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    latest_plan = render_plan_files[0] if render_plan_files else None
    return {
        "status": "succeeded",
        "outputPath": str(latest_output),
        "downloadFileName": latest_output.name,
        "renderPlanPath": str(latest_plan) if latest_plan is not None else None,
        "updatedAt": datetime.fromtimestamp(latest_output.stat().st_mtime, UTC).isoformat(),
    }


def _build_segment(
    event_id: str,
    segment_index: int,
    start_time: float,
    end_time: float,
    view: dict[str, str],
    export_format: str,
) -> NormalizedSegment | None:
    if end_time <= start_time:
        return None

    visible_cameras = _get_visible_camera_keys(view["layout"], view["cameraKey"])
    return NormalizedSegment(
        id=f"seg-{segment_index:03d}",
        event_id=event_id,
        timeline_start=_round_time(start_time),
        timeline_end=_round_time(end_time),
        layout=view["layout"],
        primary_camera=view["cameraKey"],
        visible_cameras=visible_cameras,
        export_format=export_format,
        label=None,
        notes=None,
        playback_rate=1.0,
    )


def _get_visible_camera_keys(layout: str, primary_camera: str) -> list[str]:
    if primary_camera not in CAMERA_LAYOUT_SEQUENCE:
        return [primary_camera]

    if layout == "single":
        return [primary_camera]

    current_index = CAMERA_LAYOUT_SEQUENCE.index(primary_camera)
    previous_camera = CAMERA_LAYOUT_SEQUENCE[(current_index - 1) % len(CAMERA_LAYOUT_SEQUENCE)]
    if layout == "double":
        return [previous_camera, primary_camera]

    next_camera = CAMERA_LAYOUT_SEQUENCE[(current_index + 1) % len(CAMERA_LAYOUT_SEQUENCE)]
    return [primary_camera, previous_camera, next_camera]


def _build_media_index(event_dir: Path, footage_root: Path) -> list[MediaClip]:
    clip_rows: list[dict[str, object]] = []
    segment_timestamps = []
    for clip_file in sorted(event_dir.glob("*.mp4")):
        segment_key, camera_key = _split_clip_stem(clip_file.stem)
        if camera_key not in CAMERA_ORDER:
            continue
        segment_timestamp = _infer_event_timestamp(segment_key)
        if segment_timestamp is None:
            continue
        segment_timestamps.append(segment_timestamp)
        clip_rows.append(
            {
                "clip_file": clip_file,
                "segment_key": segment_key,
                "camera_key": camera_key,
                "segment_timestamp": segment_timestamp,
            }
        )

    if not clip_rows or not segment_timestamps:
        return []

    first_timestamp = min(segment_timestamps)
    clip_rows.sort(key=lambda row: (str(row["camera_key"]), row["segment_timestamp"]))
    media_index: list[MediaClip] = []
    timeline_cursor_by_camera: dict[str, float] = {}
    previous_wallclock_end_by_camera: dict[str, float] = {}

    for row in clip_rows:
        clip_file = row["clip_file"]
        assert isinstance(clip_file, Path)
        probe = _probe_video(clip_file)
        duration = probe["duration"]
        wallclock_start_time = (row["segment_timestamp"] - first_timestamp).total_seconds()
        clip_start_time = timeline_cursor_by_camera.get(str(row["camera_key"]), 0.0)
        clip_end_time = clip_start_time + probe["duration"]
        relative_file_path = str(clip_file.relative_to(footage_root))
        camera_key = str(row["camera_key"])

        has_gap_after_previous = False
        previous_wallclock_end = previous_wallclock_end_by_camera.get(camera_key)
        if previous_wallclock_end is not None:
            gap = wallclock_start_time - previous_wallclock_end
            if gap > 0.25:
                has_gap_after_previous = True

        media_clip = MediaClip(
            absolute_file_path=str(clip_file.resolve()),
            relative_file_path=relative_file_path,
            camera_key=camera_key,
            segment_key=str(row["segment_key"]),
            clip_start_time=_round_time(clip_start_time),
            clip_end_time=_round_time(clip_end_time),
            duration=_round_time(duration),
            frame_rate=probe["frame_rate"],
            width=probe["width"],
            height=probe["height"],
            codec_name=probe["codec_name"],
            has_telemetry_sidecar=(event_dir / f"{row['segment_key']}-telemetry.sei.bin").is_file(),
            has_coverage_gap_after=has_gap_after_previous,
        )
        media_index.append(media_clip)
        timeline_cursor_by_camera[camera_key] = clip_end_time
        previous_wallclock_end_by_camera[camera_key] = wallclock_start_time + duration

    return media_index


def _probe_video(clip_file: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(clip_file),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    format_payload = payload.get("format", {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not isinstance(video_stream, dict):
        raise ValueError(f"No video stream found in {clip_file}")

    raw_duration = video_stream.get("duration", format_payload.get("duration", 0))
    duration = float(raw_duration) if raw_duration is not None else 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Could not determine duration for {clip_file}")

    raw_frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
    frame_rate = float(Fraction(str(raw_frame_rate))) if raw_frame_rate not in {"0/0", "0"} else 30.0
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    codec_name = str(video_stream.get("codec_name") or "unknown")
    return {
        "duration": duration,
        "frame_rate": frame_rate if math.isfinite(frame_rate) and frame_rate > 0 else 30.0,
        "width": width,
        "height": height,
        "codec_name": codec_name,
    }


def _pick_render_frame_rate(media_index: list[MediaClip]) -> float:
    frame_rates = [clip.frame_rate for clip in media_index if clip.frame_rate > 0]
    if not frame_rates:
        return 30.0
    return max(frame_rates)


def _get_layout_slot_specs(layout: str, primary_camera: str, frame_width: int, frame_height: int) -> list[dict[str, object]]:
    horizontal_padding = _scale_stage_pixels(STAGE_PADDING_AT_BASE_WIDTH, frame_width)
    double_gap = _scale_stage_pixels(DOUBLE_LAYOUT_GAP_AT_BASE_WIDTH, frame_width)
    usable_width = max(0, frame_width - (horizontal_padding * 2))
    visible_cameras = _get_visible_camera_keys(layout, primary_camera)
    if layout == "single":
        return [{
            "camera": visible_cameras[0],
            "x": horizontal_padding,
            "y": 0,
            "width": usable_width,
            "height": frame_height,
        }]
    if layout == "double":
        left_width, right_width = _split_even_slot_widths(max(0, usable_width - double_gap))
        return [
            {
                "camera": visible_cameras[0],
                "x": horizontal_padding,
                "y": 0,
                "width": left_width,
                "height": frame_height,
            },
            {
                "camera": visible_cameras[1],
                "x": horizontal_padding + left_width + double_gap,
                "y": 0,
                "width": right_width,
                "height": frame_height,
            },
        ]

    top_height = math.floor(frame_height * (2 / 3))
    bottom_height = frame_height - top_height
    bottom_shell_width = min(usable_width // 2, math.floor(bottom_height * (16 / 9)))
    center_x = horizontal_padding + (usable_width / 2)
    left_x = int(round(center_x - bottom_shell_width))
    right_x = int(round(center_x))
    return [
        {
            "camera": visible_cameras[0],
            "x": horizontal_padding,
            "y": 0,
            "width": usable_width,
            "height": top_height,
        },
        {
            "camera": visible_cameras[1],
            "x": left_x,
            "y": top_height,
            "width": bottom_shell_width,
            "height": bottom_height,
        },
        {
            "camera": visible_cameras[2],
            "x": right_x,
            "y": top_height,
            "width": bottom_shell_width,
            "height": bottom_height,
        },
    ]


def _resolve_fragments(
    media_index: list[MediaClip],
    camera_key: str,
    timeline_start: float,
    timeline_end: float,
) -> list[RenderFragment]:
    fragments: list[RenderFragment] = []
    for clip in media_index:
        if clip.camera_key != camera_key:
            continue
        overlap_start = max(timeline_start, clip.clip_start_time)
        overlap_end = min(timeline_end, clip.clip_end_time)
        if overlap_end <= overlap_start:
            continue
        source_in = overlap_start - clip.clip_start_time
        source_out = overlap_end - clip.clip_start_time
        fragments.append(
            RenderFragment(
                sourceClip=clip.absolute_file_path,
                sourceIn=_round_time(source_in),
                sourceOut=_round_time(source_out),
            )
        )
    return fragments


def _render_segment(
    segment: dict[str, object],
    event_dir: Path,
    event_driver_assist_display: dict[str, object] | None,
    event_base_timestamp: datetime | None,
    event_location_label: str | None,
    frame_size: dict[str, int],
    frame_rate: float,
    media_clips_by_path: dict[str, dict[str, object]],
    output_path: Path,
) -> None:
    segment_duration = float(segment["renderTimelineEnd"]) - float(segment["renderTimelineStart"])
    if segment_duration <= 0:
        raise ValueError(f"Segment {segment['segmentId']} has no renderable duration.")

    base_output_path = output_path.with_name(f"{output_path.stem}.base.mp4")
    telemetry_output_path = output_path.with_name(f"{output_path.stem}.overlay.mov")
    inputs: list[str] = []
    filter_parts: list[str] = []
    slot_output_labels: list[str] = []
    inputs.extend([
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={frame_size['width']}x{frame_size['height']}:r={frame_rate}:d={segment_duration}",
    ])
    filter_parts.append("[0:v]setpts=PTS-STARTPTS,setsar=1,format=yuv420p[stage_bg]")
    input_index = 1

    for slot_index, slot in enumerate(segment["slots"]):
        slot_label = f"slot{slot_index}"
        fragment_labels: list[str] = []
        consumed_duration = 0.0
        for fragment_index, fragment in enumerate(slot["fragments"]):
            inputs.extend(["-i", str(fragment["sourceClip"])])
            filter_parts.append(
                f"[{input_index}:v]trim=start={fragment['sourceIn']}:end={fragment['sourceOut']},setpts=PTS-STARTPTS,"
                f"fps={frame_rate:.6f},scale=w={slot['width']}:h={slot['height']}:force_original_aspect_ratio=decrease,"
                f"pad={slot['width']}:{slot['height']}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
                f"[{slot_label}_frag{fragment_index}]"
            )
            fragment_labels.append(f"[{slot_label}_frag{fragment_index}]")
            consumed_duration += float(fragment["sourceOut"]) - float(fragment["sourceIn"])
            input_index += 1

        remaining_duration = max(0.0, segment_duration - consumed_duration)
        if not fragment_labels:
            inputs.extend([
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={slot['width']}x{slot['height']}:r={frame_rate}:d={segment_duration}",
            ])
            filter_parts.append(
                f"[{input_index}:v]setpts=PTS-STARTPTS,fps={frame_rate:.6f},setsar=1,format=yuv420p[{slot_label}_base]"
            )
            input_index += 1
            slot_base_label = f"[{slot_label}_base]"
        else:
            if len(fragment_labels) == 1:
                filter_parts.append(f"{fragment_labels[0]}copy[{slot_label}_joined]")
            else:
                filter_parts.append(
                    f"{''.join(fragment_labels)}concat=n={len(fragment_labels)}:v=1:a=0[{slot_label}_joined]"
                )
            slot_base_label = f"[{slot_label}_joined]"
            if remaining_duration > 0.001:
                inputs.extend([
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={slot['width']}x{slot['height']}:r={frame_rate}:d={remaining_duration}",
                ])
                filter_parts.append(
                    f"[{input_index}:v]setpts=PTS-STARTPTS,fps={frame_rate:.6f},setsar=1,format=yuv420p[{slot_label}_pad]"
                )
                filter_parts.append(f"{slot_base_label}[{slot_label}_pad]concat=n=2:v=1:a=0[{slot_label}_filled]")
                input_index += 1
                slot_base_label = f"[{slot_label}_filled]"

        slot_output_labels.append(slot_base_label)

    canvas_label = "[stage_bg]"
    for slot_index, slot in enumerate(segment["slots"]):
        next_canvas_label = "[segment_out]" if slot_index == len(segment["slots"]) - 1 else f"[stage_canvas_{slot_index}]"
        filter_parts.append(
            f"{canvas_label}{slot_output_labels[slot_index]}overlay=x={slot['x']}:y={slot['y']}:eof_action=pass{next_canvas_label}"
        )
        canvas_label = next_canvas_label

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[segment_out]",
            "-r",
            f"{frame_rate:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(base_output_path),
        ]
    )

    if (
        not segment.get("overlay", {}).get("telemetry")
        and event_base_timestamp is None
        and not event_location_label
    ):
        shutil.move(str(base_output_path), str(output_path))
        return

    overlay_created = _render_segment_telemetry_overlay(
        segment=segment,
        event_dir=event_dir,
        event_driver_assist_display=event_driver_assist_display,
        event_base_timestamp=event_base_timestamp,
        event_location_label=event_location_label,
        frame_size=frame_size,
        frame_rate=frame_rate,
        media_clips_by_path=media_clips_by_path,
        output_path=telemetry_output_path,
    )
    if not overlay_created:
        shutil.move(str(base_output_path), str(output_path))
        return

    try:
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(base_output_path),
                "-i",
                str(telemetry_output_path),
                "-filter_complex",
                "[0:v][1:v]overlay=0:0:format=auto[segment_out]",
                "-map",
                "[segment_out]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    finally:
        if base_output_path.exists():
            base_output_path.unlink()
        if telemetry_output_path.exists():
            telemetry_output_path.unlink()


def _render_segment_telemetry_overlay(
    segment: dict[str, object],
    event_dir: Path,
    event_driver_assist_display: dict[str, object] | None,
    event_base_timestamp: datetime | None,
    event_location_label: str | None,
    frame_size: dict[str, int],
    frame_rate: float,
    media_clips_by_path: dict[str, dict[str, object]],
    output_path: Path,
) -> bool:
    timeline_map = _build_segment_reference_timeline(segment, media_clips_by_path)
    if not timeline_map:
        return False

    safe_zones = _get_safe_zone_rects(segment, frame_size, media_clips_by_path)
    route_map_overlay = _load_route_map_overlay(event_dir, safe_zones.get("topRight"))
    if (
        safe_zones["left"] is None
        and safe_zones["right"] is None
        and safe_zones["topLeft"] is None
        and route_map_overlay is None
        and event_driver_assist_display is None
        and event_base_timestamp is None
        and not event_location_label
    ):
        return False

    overlay_process = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgba",
            "-video_size",
            f"{frame_size['width']}x{frame_size['height']}",
            "-framerate",
            f"{frame_rate:.6f}",
            "-i",
            "-",
            "-an",
            "-c:v",
            "qtrle",
            str(output_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frame_count = max(1, math.ceil((float(segment["renderTimelineEnd"]) - float(segment["renderTimelineStart"])) * frame_rate))
    rendered_any_overlay = False
    try:
        assert overlay_process.stdin is not None
        for frame_index in range(frame_count):
            segment_time = min((frame_index + 0.5) / frame_rate, timeline_map[-1]["outputEnd"])
            telemetry_point = _resolve_timeline_point(segment_time, timeline_map)
            overlay_frame, has_overlay = _draw_telemetry_frame(
                frame_size=frame_size,
                safe_zones=safe_zones,
                segment_time=segment_time,
                telemetry_point=telemetry_point,
                route_map_overlay=route_map_overlay,
                event_driver_assist_display=event_driver_assist_display,
                event_base_timestamp=event_base_timestamp,
                event_location_label=event_location_label,
            )
            rendered_any_overlay = rendered_any_overlay or has_overlay
            overlay_process.stdin.write(overlay_frame.tobytes())
        overlay_process.stdin.close()
        stderr = overlay_process.stderr.read().decode("utf-8", errors="ignore") if overlay_process.stderr else ""
        return_code = overlay_process.wait()
    finally:
        if overlay_process.stdin and not overlay_process.stdin.closed:
            overlay_process.stdin.close()

    if return_code != 0:
        raise RuntimeError(stderr.strip() or "Could not render telemetry overlay.")
    if not rendered_any_overlay:
        if output_path.exists():
            output_path.unlink()
        return False
    return True


def _build_segment_reference_timeline(
    segment: dict[str, object],
    media_clips_by_path: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    reference_slot = max(
        segment["slots"],
        key=lambda slot: sum(float(fragment["sourceOut"]) - float(fragment["sourceIn"]) for fragment in slot["fragments"]),
        default=None,
    )
    if reference_slot is None:
        return []

    timeline_entries: list[dict[str, object]] = []
    output_cursor = 0.0
    for fragment in reference_slot["fragments"]:
        fragment_duration = float(fragment["sourceOut"]) - float(fragment["sourceIn"])
        if fragment_duration <= 0:
            continue
        clip_metadata = media_clips_by_path.get(str(fragment["sourceClip"]))
        if clip_metadata is None:
            continue
        segment_key, _ = _split_clip_stem(Path(str(fragment["sourceClip"])).stem)
        timeline_entries.append(
            {
                "outputStart": output_cursor,
                "outputEnd": output_cursor + fragment_duration,
                "sourceClip": str(fragment["sourceClip"]),
                "segmentKey": segment_key,
                "clipStartTime": float(clip_metadata["clip_start_time"]),
                "sourceIn": float(fragment["sourceIn"]),
            }
        )
        output_cursor += fragment_duration
    return timeline_entries


def _resolve_timeline_point(segment_time: float, timeline_map: list[dict[str, object]]) -> dict[str, object] | None:
    for entry in timeline_map:
        if segment_time > float(entry["outputEnd"]):
            continue
        if segment_time < float(entry["outputStart"]):
            continue
        offset = segment_time - float(entry["outputStart"])
        clip_time = float(entry["sourceIn"]) + offset
        return {
            "sourceClip": entry["sourceClip"],
            "segmentKey": entry["segmentKey"],
            "clipTime": clip_time,
            "eventTime": float(entry["clipStartTime"]) + clip_time,
        }
    return None


def _draw_telemetry_frame(
    frame_size: dict[str, int],
    safe_zones: dict[str, tuple[float, float, float, float] | None],
    segment_time: float,
    telemetry_point: dict[str, object] | None,
    route_map_overlay: dict[str, object] | None = None,
    event_driver_assist_display: dict[str, object] | None = None,
    event_base_timestamp: datetime | None = None,
    event_location_label: str | None = None,
) -> tuple[Image.Image, bool]:
    image = Image.new("RGBA", (int(frame_size["width"]), int(frame_size["height"])), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    sample = None
    if telemetry_point is not None:
        sidecar_path = Path(str(telemetry_point["sourceClip"])).with_name(f"{telemetry_point['segmentKey']}-telemetry.sei.bin")
        sample = _get_telemetry_sample(sidecar_path, float(telemetry_point["clipTime"]))

    has_overlay = False
    left_zone = safe_zones.get("left")
    right_zone = safe_zones.get("right")
    top_left_zone = safe_zones.get("topLeft")
    top_right_zone = safe_zones.get("topRight")
    if left_zone is not None:
        has_overlay = _draw_left_safe_zone(image, draw, left_zone, sample) or has_overlay
    if right_zone is not None:
        has_overlay = _draw_right_safe_zone(image, draw, right_zone, sample, event_driver_assist_display) or has_overlay
    if top_right_zone is not None and route_map_overlay is not None:
        has_overlay = _draw_top_right_route_overlay(image, draw, top_right_zone, route_map_overlay, sample) or has_overlay
    if top_left_zone is not None:
        timeline_offset_seconds = float(segment_time)
        if telemetry_point is not None and isinstance(telemetry_point.get("eventTime"), int | float):
            timeline_offset_seconds = float(telemetry_point["eventTime"])
        event_date_label, event_time_label = _get_overlay_datetime_labels(event_base_timestamp, timeline_offset_seconds)
        has_overlay = _draw_top_left_safe_zone(
            image,
            draw,
            top_left_zone,
            event_date_label,
            event_time_label,
            event_location_label,
        ) or has_overlay
    return image, has_overlay


def _draw_top_left_safe_zone(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    event_date_label: str | None,
    event_time_label: str | None,
    event_location_label: str | None,
) -> bool:
    lines = [
        value.strip()
        for value in (event_date_label, event_time_label, event_location_label)
        if isinstance(value, str) and value.strip()
    ]
    if not lines:
        return False

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width < 1 or height < 1:
        return False

    padding = max(6.0, width * 0.08)
    inner_left = left + padding
    inner_top = top + padding
    inner_right = max(inner_left, right - padding)
    inner_bottom = max(inner_top, bottom - padding)
    if inner_right - inner_left < 1 or inner_bottom - inner_top < 1:
        return False

    title_font = _fit_safe_zone_text_font(rect, 0.09, 0.08)
    title_letter_spacing = _get_text_letter_spacing(title_font, 0.03)
    title_text = _truncate_text_to_width(draw, "SentryManager", title_font, inner_right - inner_left, title_letter_spacing)
    title_height = _measure_tracked_text(draw, "SentryManager", title_font, title_letter_spacing)[1]
    title_rect = (
        inner_left,
        inner_top,
        inner_right,
        min(inner_bottom, inner_top + title_height),
    )
    if title_text:
        _draw_centered_text(
            draw,
            title_rect,
            title_text,
            title_font,
            fill=(255, 255, 255, 255),
            shadow=False,
            letter_spacing=title_letter_spacing,
        )

    title_gap = max(_scale_stage_pixels(2.0, width), height * 0.01)
    icon_top = title_rect[3] + title_gap if title_text else inner_top
    icon_size = max(14, int(round(width * 0.5)))
    icon_rect = (
        inner_left,
        icon_top,
        inner_right,
        min(inner_bottom, icon_top + icon_size),
    )
    icon_rendered = _paste_centered_svg_icon(
        image,
        icon_rect,
        "sentry-eye.svg",
        icon_size,
        asset_root=IMAGE_ASSET_ROOT,
    )
    icon_gap = max(_scale_stage_pixels(2.0, width), height * 0.01)
    text_top_limit = icon_rect[3] + icon_gap if icon_rendered else icon_top
    if text_top_limit >= inner_bottom:
        text_top_limit = inner_top

    font = _fit_safe_zone_text_font(rect, 0.105, 0.095)
    letter_spacing = _get_text_letter_spacing(font, 0.02)
    fitted_lines = [
        _truncate_text_to_width(draw, line, font, inner_right - inner_left, letter_spacing)
        for line in lines
    ]
    fitted_lines = [line for line in fitted_lines if line]
    if not fitted_lines:
        return False

    line_gap = max(_scale_stage_pixels(1.0, width), height * 0.012)
    line_height = _measure_tracked_text(draw, "00", font, letter_spacing)[1]
    block_height = (line_height * len(fitted_lines)) + (line_gap * max(0, len(fitted_lines) - 1))
    block_bottom = inner_bottom
    current_top = max(text_top_limit, block_bottom - block_height)
    for line in fitted_lines:
        line_rect = (
            inner_left,
            current_top,
            inner_right,
            current_top + line_height,
        )
        _draw_centered_text(
            draw,
            line_rect,
            line,
            font,
            fill=(255, 255, 255, 255),
            shadow=False,
            letter_spacing=letter_spacing,
        )
        current_top += line_height + line_gap
    return True


def _draw_top_right_route_overlay(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    route_map_overlay: dict[str, object],
    sample: dict[str, object] | None,
) -> bool:
    route_map_image = route_map_overlay.get("image")
    projection = route_map_overlay.get("projection")
    if not isinstance(route_map_image, Image.Image) or not isinstance(projection, dict):
        return False

    left, top, right, bottom = rect
    width = max(1, int(round(right - left)))
    height = max(1, int(round(bottom - top)))
    if width < 1 or height < 1:
        return False

    image_x = int(round(left))
    image_y = int(round(top))
    if route_map_image.size != (width, height):
        route_map_image = route_map_image.resize((width, height), Image.Resampling.LANCZOS)
    image.alpha_composite(route_map_image, (image_x, image_y))

    dot_position = _project_route_dot_to_overlay(sample, projection, width, height)
    if dot_position is None:
        return True

    dot_radius = max(2.0, (min(width, height) * (ROUTE_DOT_RADIUS_AT_CANVAS / ROUTE_MAP_CANVAS_SIZE)))
    dot_cx = image_x + dot_position[0]
    dot_cy = image_y + dot_position[1]
    dot_rect = (
        dot_cx - dot_radius,
        dot_cy - dot_radius,
        dot_cx + dot_radius,
        dot_cy + dot_radius,
    )
    draw.ellipse(dot_rect, fill=ROUTE_DOT_FILL, outline=ROUTE_DOT_STROKE, width=1)
    return True


def _project_route_dot_to_overlay(
    sample: dict[str, object] | None,
    projection: dict[str, float],
    width: int,
    height: int,
) -> tuple[float, float] | None:
    if sample is None:
        return None

    presence_bits = int(sample.get("presenceBits") or 0)
    if (presence_bits & LATITUDE_PRESENT_MASK) == 0 or (presence_bits & LONGITUDE_PRESENT_MASK) == 0:
        return None

    latitude_e7 = sample.get("latitudeE7")
    longitude_e7 = sample.get("longitudeE7")
    if not isinstance(latitude_e7, int | float) or not isinstance(longitude_e7, int | float):
        return None

    mean_lat = projection["mean_lat"]
    mean_lon = projection["mean_lon"]
    cos_lat = projection["cos_lat"]
    min_x = projection["min_x"]
    min_y = projection["min_y"]
    span = projection["span"]
    if not math.isfinite(span) or span <= 0:
        return None

    latitude = float(latitude_e7) / 10_000_000
    longitude = float(longitude_e7) / 10_000_000
    projected_x = (longitude - mean_lon) * cos_lat
    projected_y = latitude - mean_lat
    drawable = ROUTE_MAP_CANVAS_SIZE - (ROUTE_MAP_PADDING * 2)
    normalized_x = ROUTE_MAP_PADDING + (((projected_x - min_x) / span) * drawable)
    normalized_y = ROUTE_MAP_CANVAS_SIZE - (ROUTE_MAP_PADDING + (((projected_y - min_y) / span) * drawable))
    if not math.isfinite(normalized_x) or not math.isfinite(normalized_y):
        return None

    clamped_x = max(0.0, min(ROUTE_MAP_CANVAS_SIZE, normalized_x))
    clamped_y = max(0.0, min(ROUTE_MAP_CANVAS_SIZE, normalized_y))
    offset_x, offset_y, draw_width, draw_height = _get_route_canvas_contain_rect(width, height)
    if draw_width <= 0 or draw_height <= 0:
        return None
    return (
        offset_x + ((clamped_x / ROUTE_MAP_CANVAS_SIZE) * draw_width),
        offset_y + ((clamped_y / ROUTE_MAP_CANVAS_SIZE) * draw_height),
    )


def _get_route_canvas_contain_rect(width: int, height: int) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    scale = min(width / ROUTE_MAP_CANVAS_SIZE, height / ROUTE_MAP_CANVAS_SIZE)
    draw_width = ROUTE_MAP_CANVAS_SIZE * scale
    draw_height = ROUTE_MAP_CANVAS_SIZE * scale
    offset_x = (width - draw_width) / 2
    offset_y = (height - draw_height) / 2
    return (offset_x, offset_y, draw_width, draw_height)


def _load_route_map_overlay(
    event_dir: Path,
    top_right_safe_zone: tuple[float, float, float, float] | None,
) -> dict[str, object] | None:
    if top_right_safe_zone is None:
        return None

    left, top, right, bottom = top_right_safe_zone
    target_width = max(1, int(round(right - left)))
    target_height = max(1, int(round(bottom - top)))
    if target_width < 1 or target_height < 1:
        return None

    route_svg_path = event_dir / EVENT_ROUTE_SVG_NAME
    if not route_svg_path.is_file():
        return None

    try:
        svg_payload = route_svg_path.read_text(encoding="utf-8")
    except OSError:
        return None

    projection = _parse_route_projection(svg_payload)
    if projection is None:
        return None

    route_map_image = _render_svg_to_rgba_image(route_svg_path, target_width, target_height)
    if route_map_image is None:
        return None

    return {
        "projection": projection,
        "image": route_map_image,
    }


def _parse_route_projection(svg_payload: str) -> dict[str, float] | None:
    def parse_attribute(attribute_name: str) -> float | None:
        match = re.search(rf'{attribute_name}="([^"]+)"', svg_payload)
        if match is None:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    projection = {
        "mean_lat": parse_attribute("data-route-mean-lat"),
        "mean_lon": parse_attribute("data-route-mean-lon"),
        "cos_lat": parse_attribute("data-route-cos-lat"),
        "min_x": parse_attribute("data-route-min-x"),
        "min_y": parse_attribute("data-route-min-y"),
        "span": parse_attribute("data-route-span"),
    }
    if any(value is None for value in projection.values()):
        return None

    span = float(projection["span"])
    if span <= 0:
        return None

    return {
        key: float(value)
        for key, value in projection.items()
        if value is not None
    }


def _render_svg_to_rgba_image(svg_path: Path, width: int, height: int) -> Image.Image | None:
    if width < 1 or height < 1:
        return None

    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(svg_path),
            "-vf",
            (
                f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0"
            ),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None

    try:
        image = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
    except OSError:
        return None

    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def _draw_left_safe_zone(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    sample: dict[str, object] | None,
) -> bool:
    cells = _get_safe_zone_cells(rect)
    rendered = False
    if sample and sample["blinkerLeftOn"]:
        if not _paste_centered_svg_icon(image, cells[0], "indicator-left.svg", _get_safe_zone_icon_size(rect, emphasized=False)):
            _draw_centered_text(draw, cells[0], "<", _fit_font(cells[0], 0.7))
        rendered = True
    if sample and sample["headingLabel"]:
        if not _draw_heading_cell(image, draw, cells[1], rect, sample):
            _draw_centered_text(draw, cells[1], str(sample["headingLabel"]), _fit_safe_zone_text_font(rect, 0.10, 0.10))
        rendered = True
    if sample and sample["brakeOn"]:
        if not _paste_centered_svg_icon(image, cells[2], "brake.svg", _get_safe_zone_icon_size(rect, emphasized=True)):
            _draw_centered_text(draw, cells[2], "BRAKE", _fit_font(cells[2], 0.32))
        rendered = True
    return rendered


def _draw_right_safe_zone(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    sample: dict[str, object] | None,
    event_driver_assist_display: dict[str, object] | None,
) -> bool:
    cells = _get_safe_zone_cells(rect)
    rendered = False
    if sample and sample["blinkerRightOn"]:
        if not _paste_centered_svg_icon(image, cells[0], "indicator-right.svg", _get_safe_zone_icon_size(rect, emphasized=False)):
            _draw_centered_text(draw, cells[0], ">", _fit_font(cells[0], 0.7))
        rendered = True
    if sample and sample["speedKph"] is not None:
        _draw_speed_value(draw, cells[1], rect, round(float(sample["speedKph"])))
        rendered = True
    if sample and sample["showAutopilot"]:
        icon_name = "steering-blue.svg" if sample["autopilotActive"] else "steering-white.svg"
        if not _paste_centered_svg_icon(
            image,
            cells[2],
            icon_name,
            _get_safe_zone_icon_size(rect, emphasized=True),
            rotation_degrees=float(sample.get("steeringAngleDegrees") or 0.0),
        ):
            _draw_centered_text(
                draw,
                cells[2],
                "AP",
                _fit_safe_zone_text_font(rect, 0.14, 0.11),
                fill=AUTOPILOT_ACTIVE_COLOR if sample["autopilotActive"] else TELEMETRY_COLOR,
            )
        rendered = True
    if event_driver_assist_display is not None:
        fsd_font = _fit_safe_zone_text_font(rect, 0.10, 0.088)
        _draw_centered_text(
            draw,
            cells[3],
            str(event_driver_assist_display.get("text") or ""),
            fsd_font,
            letter_spacing=_get_text_letter_spacing(fsd_font, 0.08),
        )
        rendered = True
    return rendered


def _get_event_driver_assist_display(event_processing_state: dict[str, object]) -> dict[str, object] | None:
    raw_display = event_processing_state.get("driverAssistDisplay")
    if isinstance(raw_display, dict):
        raw_label = raw_display.get("label")
        raw_percent = raw_display.get("percent")
        raw_text = raw_display.get("text")
        if isinstance(raw_label, str) and raw_label in {"FSD", "AP"} and isinstance(raw_percent, int | float):
            percent = _coerce_optional_percentage(raw_percent)
            if percent is not None:
                return {
                    "label": raw_label,
                    "percent": percent,
                    "text": raw_text if isinstance(raw_text, str) and raw_text.strip() else f"{raw_label} {round(percent)}%",
                }

    legacy_fsd_on_percent = _coerce_optional_percentage(event_processing_state.get("fsdOnPercent"))
    if legacy_fsd_on_percent is None:
        return None
    return {
        "label": "FSD",
        "percent": legacy_fsd_on_percent,
        "text": f"FSD {round(legacy_fsd_on_percent)}%",
    }


def _draw_heading_cell(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cell_rect: tuple[float, float, float, float],
    zone_rect: tuple[float, float, float, float],
    sample: dict[str, object],
) -> bool:
    heading_label = sample.get("headingLabel")
    if not isinstance(heading_label, str) or not heading_label:
        return False
    left, top, right, bottom = cell_rect
    indicator_size = _get_safe_zone_icon_size(zone_rect, emphasized=False)
    indicator_left = left + ((right - left - indicator_size) / 2)
    indicator_top = top + ((bottom - top - indicator_size) / 2)
    indicator_rect = (
        indicator_left,
        indicator_top,
        indicator_left + indicator_size,
        indicator_top + indicator_size,
    )
    rotation_degrees = float(sample.get("headingDegrees") or 0.0)
    icon_rendered = _paste_centered_svg_icon(
        image,
        indicator_rect,
        "navigation.svg",
        indicator_size,
        rotation_degrees=rotation_degrees,
    )
    _draw_centered_text(
        draw,
        indicator_rect,
        heading_label,
        _fit_safe_zone_text_font(zone_rect, 0.10, 0.10),
        fill=HEADING_LABEL_COLOR,
        shadow=False,
    )
    return icon_rendered


def _paste_centered_svg_icon(
    image: Image.Image,
    rect: tuple[float, float, float, float],
    icon_name: str,
    target_size: int,
    rotation_degrees: float = 0.0,
    asset_root: Path = MDI_ASSET_ROOT,
) -> bool:
    left, top, right, bottom = rect
    icon_size = max(12, min(target_size, int(round(min(right - left, bottom - top)))))
    icon = _load_svg_icon(icon_name, icon_size, asset_root=asset_root)
    if icon is None:
        return False
    if abs(rotation_degrees) > 0.1:
        icon = icon.rotate(-rotation_degrees, resample=Image.Resampling.BICUBIC, expand=True)
    x = int(round(left + ((right - left - icon.width) / 2)))
    y = int(round(top + ((bottom - top - icon.height) / 2)))
    image.alpha_composite(icon, (x, y))
    return True


def _get_safe_zone_icon_size(rect: tuple[float, float, float, float], emphasized: bool) -> int:
    left, top, right, bottom = rect
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    width_ratio = 0.40 if emphasized else 0.34
    height_ratio = 0.19 if emphasized else 0.16
    return max(14, int(round(min(width * width_ratio, height * height_ratio))))


def _fit_safe_zone_text_font(
    rect: tuple[float, float, float, float],
    width_ratio: float,
    height_ratio: float,
) -> ImageFont.ImageFont:
    left, top, right, bottom = rect
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    font_size = max(10, int(round(min(width * width_ratio, height * height_ratio))))
    return _load_font(font_size)


def _load_font(font_size: int) -> ImageFont.ImageFont:
    for font_path in FONT_CANDIDATES:
        if Path(font_path).is_file():
            try:
                return ImageFont.truetype(font_path, size=font_size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_speed_value(
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    zone_rect: tuple[float, float, float, float],
    speed_value: int,
) -> None:
    number_font = _fit_safe_zone_text_font(zone_rect, 0.14, 0.11)
    unit_font = _fit_safe_zone_text_font(zone_rect, 0.08, 0.07)
    unit_letter_spacing = _get_text_letter_spacing(unit_font, 0.04)
    gap = max(4, int(round((zone_rect[2] - zone_rect[0]) * 0.015)))
    number_text = str(speed_value)
    unit_text = "km/h"
    number_bbox = draw.textbbox((0, 0), number_text, font=number_font)
    unit_width, unit_height = _measure_tracked_text(draw, unit_text, unit_font, unit_letter_spacing)
    number_width = number_bbox[2] - number_bbox[0]
    number_height = number_bbox[3] - number_bbox[1]
    total_width = number_width + gap + unit_width
    left, top, right, bottom = rect
    if total_width > (right - left) * 0.95:
        scale = ((right - left) * 0.95) / total_width
        number_font = _fit_safe_zone_text_font(zone_rect, 0.14 * scale, 0.11 * scale)
        unit_font = _fit_safe_zone_text_font(zone_rect, 0.08 * scale, 0.07 * scale)
        unit_letter_spacing = _get_text_letter_spacing(unit_font, 0.04)
        number_bbox = draw.textbbox((0, 0), number_text, font=number_font)
        unit_width, unit_height = _measure_tracked_text(draw, unit_text, unit_font, unit_letter_spacing)
        number_width = number_bbox[2] - number_bbox[0]
        number_height = number_bbox[3] - number_bbox[1]
        total_width = number_width + gap + unit_width
    baseline_height = max(number_height, unit_height)
    x = int(round(left + ((right - left - total_width) / 2)))
    number_y = int(round(top + ((bottom - top - number_height) / 2)))
    unit_y = int(round(top + ((bottom - top - baseline_height) / 2) + (baseline_height - unit_height)))
    _draw_text_with_shadow(draw, (x, number_y), number_text, number_font)
    _draw_text_with_shadow(draw, (x + number_width + gap, unit_y), unit_text, unit_font, letter_spacing=unit_letter_spacing)


def _load_svg_icon(icon_name: str, target_size: int, asset_root: Path = MDI_ASSET_ROOT) -> Image.Image | None:
    cache_key = (f"{asset_root}:{icon_name}", target_size)
    cached_icon = SVG_ICON_CACHE.get(cache_key)
    if cache_key in SVG_ICON_CACHE:
        return cached_icon.copy() if cached_icon is not None else None

    icon_path = asset_root / icon_name
    if not icon_path.is_file():
        SVG_ICON_CACHE[cache_key] = None
        return None

    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(icon_path),
            "-vf",
            f"scale={target_size}:{target_size}:force_original_aspect_ratio=decrease:flags=lanczos",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        SVG_ICON_CACHE[cache_key] = None
        return None

    try:
        icon = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
    except OSError:
        SVG_ICON_CACHE[cache_key] = None
        return None

    largest_dimension = max(icon.width, icon.height)
    if largest_dimension <= 0:
        SVG_ICON_CACHE[cache_key] = None
        return None

    if largest_dimension != target_size:
        scale = target_size / largest_dimension
        resized_dimensions = (
            max(1, int(round(icon.width * scale))),
            max(1, int(round(icon.height * scale))),
        )
        icon = icon.resize(resized_dimensions, Image.Resampling.LANCZOS)
    SVG_ICON_CACHE[cache_key] = icon
    return icon.copy()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = TELEMETRY_COLOR,
    shadow: bool = True,
    letter_spacing: float = 0.0,
) -> None:
    left, top, right, bottom = rect
    text_width, text_height = _measure_tracked_text(draw, text, font, letter_spacing)
    bbox = draw.textbbox((0, 0), text, font=font)
    bbox_left = bbox[0]
    bbox_top = bbox[1]
    x = int(round(left + ((right - left - text_width) / 2) - bbox_left))
    y = int(round(top + ((bottom - top - text_height) / 2) - bbox_top))
    if shadow:
        _draw_text_with_shadow(draw, (x, y), text, font, fill=fill, letter_spacing=letter_spacing)
        return
    _draw_tracked_text(draw, (x, y), text, font, fill=fill, letter_spacing=letter_spacing)


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = TELEMETRY_COLOR,
    letter_spacing: float = 0.0,
) -> None:
    x, y = xy
    _draw_tracked_text(draw, (x, y), text, font, fill=fill, letter_spacing=letter_spacing)




def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    letter_spacing: float = 0.0,
) -> None:
    x, y = xy
    cursor_x = float(x)
    for index, character in enumerate(text):
        draw.text((cursor_x, y), character, font=font, fill=fill)
        cursor_x += _get_character_advance(font, character)
        if index < len(text) - 1:
            cursor_x += letter_spacing


def _measure_tracked_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    letter_spacing: float = 0.0,
) -> tuple[int, int]:
    if not text:
        return (0, 0)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_height = bbox[3] - bbox[1]
    text_width = int(round(sum(_get_character_advance(font, character) for character in text)))
    text_width += int(round(letter_spacing * max(0, len(text) - 1)))
    return (text_width, text_height)


def _truncate_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: float,
    letter_spacing: float = 0.0,
) -> str:
    if max_width <= 0:
        return ""
    if _measure_tracked_text(draw, text, font, letter_spacing)[0] <= max_width:
        return text

    ellipsis = "..."
    if _measure_tracked_text(draw, ellipsis, font, letter_spacing)[0] > max_width:
        return ""

    for index in range(len(text), 0, -1):
        candidate = f"{text[:index].rstrip()}{ellipsis}"
        if _measure_tracked_text(draw, candidate, font, letter_spacing)[0] <= max_width:
            return candidate
    return ellipsis


def _get_character_advance(font: ImageFont.ImageFont, character: str) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(character))
    bbox = font.getbbox(character)
    return float(bbox[2] - bbox[0])


def _get_text_letter_spacing(font: ImageFont.ImageFont, em_ratio: float) -> float:
    size = getattr(font, "size", 12)
    return float(size) * em_ratio


def _fit_font(rect: tuple[float, float, float, float], height_ratio: float) -> ImageFont.ImageFont:
    _, top, _, bottom = rect
    font_size = max(12, int(round((bottom - top) * height_ratio)))
    return _load_font(font_size)


def _get_safe_zone_cells(rect: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    padding = max(6.0, width * 0.08)
    gap = max(_scale_stage_pixels(2.5, width), height * 0.028)
    inner_left = left + padding
    inner_top = top + padding
    inner_right = max(inner_left, right - padding)
    inner_bottom = max(inner_top, bottom - padding)
    inner_height = max(0.0, inner_bottom - inner_top)
    cell_height = max(0.0, (inner_height - (gap * 3)) / 4)
    cells: list[tuple[float, float, float, float]] = []
    current_top = inner_top
    for _ in range(4):
        cells.append((inner_left, current_top, inner_right, current_top + cell_height))
        current_top += cell_height + gap
    return cells


def _get_safe_zone_rects(
    segment: dict[str, object],
    frame_size: dict[str, int],
    media_clips_by_path: dict[str, dict[str, object]],
) -> dict[str, tuple[float, float, float, float] | None]:
    master_aspect_ratio, left_aspect_ratio, right_aspect_ratio = _get_safe_zone_layout_aspect_ratios(
        segment,
        media_clips_by_path,
    )
    if master_aspect_ratio <= 0:
        return {"left": None, "right": None, "topLeft": None, "topRight": None}

    frame_width = float(frame_size["width"])
    frame_height = float(frame_size["height"])
    left_padding = float(_scale_stage_pixels(STAGE_PADDING_AT_BASE_WIDTH, frame_width))
    right_padding = float(_scale_stage_pixels(STAGE_PADDING_AT_BASE_WIDTH, frame_width))
    column_gap = 0.0 if segment.get("layout") == "triple" else float(_scale_stage_pixels(DOUBLE_LAYOUT_GAP_AT_BASE_WIDTH, frame_width))
    usable_width = max(0.0, frame_width - left_padding - right_padding)
    if usable_width <= 0 or frame_height <= 0:
        return {"left": None, "right": None, "topLeft": None, "topRight": None}

    content_rects: list[tuple[float, float, float, float]] = []

    def push_contained_rect(rect: tuple[float, float, float, float], aspect_ratio: float) -> None:
        content_rect = _get_contained_video_rect(rect, aspect_ratio)
        if content_rect is not None:
            content_rects.append(content_rect)

    push_contained_rect(
        (left_padding, 0.0, left_padding + usable_width, frame_height),
        master_aspect_ratio,
    )

    double_shell_width = max(0.0, (usable_width - column_gap) / 2)
    push_contained_rect(
        (left_padding, 0.0, left_padding + double_shell_width, frame_height),
        left_aspect_ratio,
    )
    push_contained_rect(
        (
            left_padding + double_shell_width + column_gap,
            0.0,
            left_padding + double_shell_width + column_gap + double_shell_width,
            frame_height,
        ),
        master_aspect_ratio,
    )

    triple_main_height = frame_height * (2 / 3)
    triple_bottom_height = frame_height - triple_main_height
    triple_bottom_shell_width = min(usable_width / 2, triple_bottom_height * (16 / 9))
    triple_center_x = left_padding + (usable_width / 2)

    push_contained_rect(
        (left_padding, 0.0, left_padding + usable_width, triple_main_height),
        master_aspect_ratio,
    )
    push_contained_rect(
        (
            triple_center_x - triple_bottom_shell_width,
            triple_main_height,
            triple_center_x,
            frame_height,
        ),
        left_aspect_ratio,
    )
    push_contained_rect(
        (
            triple_center_x,
            triple_main_height,
            triple_center_x + triple_bottom_shell_width,
            frame_height,
        ),
        right_aspect_ratio,
    )

    return {
        "left": _get_bottom_corner_safe_rect(content_rects, frame_width, frame_height, "left"),
        "right": _get_bottom_corner_safe_rect(content_rects, frame_width, frame_height, "right"),
        "topLeft": _get_top_corner_safe_rect(content_rects, frame_width, frame_height, "left"),
        "topRight": _get_top_corner_safe_rect(content_rects, frame_width, frame_height, "right"),
    }


def _get_safe_zone_layout_aspect_ratios(
    segment: dict[str, object],
    media_clips_by_path: dict[str, dict[str, object]],
) -> tuple[float, float, float]:
    slots = segment.get("slots", [])
    layout = str(segment.get("layout") or "single")
    if layout == "triple":
        master_slot = slots[0] if len(slots) > 0 else None
        left_slot = slots[1] if len(slots) > 1 else None
        right_slot = slots[2] if len(slots) > 2 else None
    elif layout == "double":
        left_slot = slots[0] if len(slots) > 0 else None
        master_slot = slots[1] if len(slots) > 1 else None
        right_slot = None
    else:
        master_slot = slots[0] if len(slots) > 0 else None
        left_slot = None
        right_slot = None

    master_aspect_ratio = _get_slot_aspect_ratio(master_slot, media_clips_by_path) if master_slot is not None else 16 / 9
    left_aspect_ratio = _get_slot_aspect_ratio(left_slot, media_clips_by_path) if left_slot is not None else master_aspect_ratio
    right_aspect_ratio = _get_slot_aspect_ratio(right_slot, media_clips_by_path) if right_slot is not None else master_aspect_ratio
    return master_aspect_ratio, left_aspect_ratio, right_aspect_ratio


def _get_slot_aspect_ratio(slot: dict[str, object], media_clips_by_path: dict[str, dict[str, object]]) -> float:
    fragments = slot.get("fragments", [])
    for fragment in fragments:
        clip_metadata = media_clips_by_path.get(str(fragment["sourceClip"]))
        if clip_metadata is None:
            continue
        width = float(clip_metadata.get("width") or 0)
        height = float(clip_metadata.get("height") or 0)
        if width > 0 and height > 0:
            return width / height
    return 16 / 9


def _get_contained_video_rect(
    rect: tuple[float, float, float, float],
    aspect_ratio: float,
) -> tuple[float, float, float, float] | None:
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0 or aspect_ratio <= 0:
        return None

    container_aspect_ratio = width / height
    if container_aspect_ratio > aspect_ratio:
        contained_height = height
        contained_width = contained_height * aspect_ratio
        contained_left = left + ((width - contained_width) / 2)
        return (contained_left, top, contained_left + contained_width, bottom)

    contained_width = width
    contained_height = contained_width / aspect_ratio
    contained_top = top + ((height - contained_height) / 2)
    return (left, contained_top, right, contained_top + contained_height)


def _get_bottom_corner_safe_rect(
    content_rects: list[tuple[float, float, float, float]],
    frame_width: float,
    frame_height: float,
    side: str,
) -> tuple[float, float, float, float] | None:
    breakpoints = {0.0, frame_height}
    for rect in content_rects:
        breakpoints.add(max(0.0, min(frame_height, rect[1])))
        breakpoints.add(max(0.0, min(frame_height, rect[3])))

    best_rect: tuple[float, float, float, float] | None = None
    best_area = 0.0
    for top in sorted(breakpoints):
        available_width = frame_width
        for rect in content_rects:
            if rect[3] <= top or rect[1] >= frame_height:
                continue
            if side == "left":
                available_width = min(available_width, rect[0])
            else:
                available_width = min(available_width, frame_width - rect[2])

        height = frame_height - top
        width = max(0.0, available_width)
        area = width * height
        if area <= best_area or width < 1 or height < 1:
            continue
        rect_top = frame_height - height
        if side == "left":
            best_rect = (0.0, rect_top, width, frame_height)
        else:
            best_rect = (frame_width - width, rect_top, frame_width, frame_height)
        best_area = area
    return best_rect


def _get_top_corner_safe_rect(
    content_rects: list[tuple[float, float, float, float]],
    frame_width: float,
    frame_height: float,
    side: str,
) -> tuple[float, float, float, float] | None:
    breakpoints = {0.0, frame_height}
    for rect in content_rects:
        breakpoints.add(max(0.0, min(frame_height, rect[1])))
        breakpoints.add(max(0.0, min(frame_height, rect[3])))

    best_rect: tuple[float, float, float, float] | None = None
    best_area = 0.0
    for bottom in sorted(breakpoints):
        available_width = frame_width
        for rect in content_rects:
            if rect[3] <= 0 or rect[1] >= bottom:
                continue
            if side == "left":
                available_width = min(available_width, rect[0])
            else:
                available_width = min(available_width, frame_width - rect[2])

        height = max(0.0, bottom)
        width = max(0.0, available_width)
        area = width * height
        if area <= best_area or width < 1 or height < 1:
            continue
        if side == "left":
            best_rect = (0.0, 0.0, width, height)
        else:
            best_rect = (frame_width - width, 0.0, frame_width, height)
        best_area = area
    return best_rect


def _slot_has_telemetry(slot: dict[str, object]) -> bool:
    for fragment in slot.get("fragments", []):
        segment_key, _ = _split_clip_stem(Path(str(fragment["sourceClip"])).stem)
        sidecar_path = Path(str(fragment["sourceClip"])).with_name(f"{segment_key}-telemetry.sei.bin")
        if sidecar_path.is_file():
            return True
    return False


def _load_event_processing_state(event_dir: Path) -> dict[str, object]:
    processing_state_path = event_dir / "sentrymanager.json"
    if not processing_state_path.is_file():
        return {}
    try:
        payload = json.loads(processing_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_event_payload(event_dir: Path) -> dict[str, object] | None:
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


def _get_event_location_label(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None

    street = payload.get("street")
    city = payload.get("city")
    location_parts = [value.strip() for value in (street, city) if isinstance(value, str) and value.strip()]
    if not location_parts:
        return None
    return ", ".join(location_parts)


def _get_event_base_timestamp(payload: dict[str, object] | None, event_dir: Path) -> datetime | None:
    timestamp = None
    if isinstance(payload, dict):
        raw_timestamp = payload.get("timestamp")
        if isinstance(raw_timestamp, str) and raw_timestamp.strip():
            try:
                timestamp = datetime.fromisoformat(raw_timestamp.strip())
            except ValueError:
                timestamp = None

    if timestamp is None:
        timestamp = _infer_event_timestamp(event_dir.name)

    return timestamp


def _get_overlay_datetime_labels(base_timestamp: datetime | None, offset_seconds: float) -> tuple[str | None, str | None]:
    if base_timestamp is None:
        return None, None

    timeline_seconds = max(0, float(offset_seconds))
    overlay_timestamp = base_timestamp + timedelta(seconds=timeline_seconds)
    return overlay_timestamp.strftime("%d-%m-%Y"), overlay_timestamp.strftime("%H:%M")


def _coerce_optional_percentage(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        return None
    return max(0.0, min(100.0, numeric_value))


def _get_telemetry_sample(sidecar_path: Path, clip_time_seconds: float) -> dict[str, object] | None:
    telemetry = _load_telemetry_sidecar(sidecar_path)
    if telemetry is None:
        return None

    sample_index = _find_telemetry_sample_index(telemetry["time_ms"], max(0, int(round(clip_time_seconds * 1000))))
    if sample_index < 0:
        return None

    presence_bits = int(telemetry["presence_bits"][sample_index])
    flags = int(telemetry["flags"][sample_index])
    autopilot_state = int(telemetry["autopilot_state"][sample_index])
    speed_kph = float(telemetry["speed_cmps"][sample_index]) * 0.036 if presence_bits & SPEED_PRESENT_MASK else None
    heading_label = None
    heading_degrees = None
    if presence_bits & HEADING_PRESENT_MASK:
        heading_degrees = float(telemetry["heading_cdeg"][sample_index]) / 100
        heading_label = _get_compass_direction_label(heading_degrees)
    show_autopilot = bool(presence_bits & (AUTOPILOT_PRESENT_MASK | STEERING_ANGLE_PRESENT_MASK))
    steering_angle_degrees = float(telemetry["steering_tenths_deg"][sample_index]) / 10 if presence_bits & STEERING_ANGLE_PRESENT_MASK else 0.0

    return {
        "speedKph": speed_kph,
        "blinkerLeftOn": bool((presence_bits & BLINKER_LEFT_PRESENT_MASK) and (flags & BLINKER_LEFT_FLAG_MASK)),
        "blinkerRightOn": bool((presence_bits & BLINKER_RIGHT_PRESENT_MASK) and (flags & BLINKER_RIGHT_FLAG_MASK)),
        "brakeOn": bool((presence_bits & BRAKE_PRESENT_MASK) and (flags & BRAKE_FLAG_MASK)),
        "headingDegrees": heading_degrees,
        "headingLabel": heading_label,
        "showAutopilot": show_autopilot,
        "autopilotActive": bool((presence_bits & AUTOPILOT_PRESENT_MASK) and autopilot_state != AUTOPILOT_NONE_STATE),
        "steeringAngleDegrees": steering_angle_degrees,
        "presenceBits": presence_bits,
        "latitudeE7": int(telemetry["latitude_e7"][sample_index]) if presence_bits & LATITUDE_PRESENT_MASK else None,
        "longitudeE7": int(telemetry["longitude_e7"][sample_index]) if presence_bits & LONGITUDE_PRESENT_MASK else None,
    }


def _load_telemetry_sidecar(sidecar_path: Path) -> dict[str, list[int]] | None:
    if not sidecar_path.is_file():
        return None
    try:
        payload = sidecar_path.read_bytes()
    except OSError:
        return None
    if len(payload) < HEADER_SIZE:
        return None

    magic = payload[:4]
    if magic != FORMAT_MAGIC:
        return None
    version = int.from_bytes(payload[4:6], "little")
    header_size = int.from_bytes(payload[6:8], "little")
    sample_count = int.from_bytes(payload[8:12], "little")
    if version != FORMAT_VERSION or header_size < HEADER_SIZE or sample_count <= 0:
        return None

    telemetry: dict[str, list[int]] = {}
    for index, (column_name, struct_format) in enumerate(COLUMN_DEFINITIONS):
        offset_start = 20 + (index * 4)
        column_offset = int.from_bytes(payload[offset_start: offset_start + 4], "little")
        if column_offset <= 0:
            telemetry[column_name] = []
            continue
        item_size = struct.calcsize(f"<{struct_format}")
        column_end = column_offset + (item_size * sample_count)
        if column_end > len(payload):
            return None
        column_values = []
        for value_index in range(sample_count):
            value_offset = column_offset + (value_index * item_size)
            column_values.append(struct.unpack_from(f"<{struct_format}", payload, value_offset)[0])
        telemetry[column_name] = column_values
    return telemetry


def _find_telemetry_sample_index(time_values: list[int], target_time_ms: int) -> int:
    if not time_values:
        return -1
    low = 0
    high = len(time_values) - 1
    result = -1
    while low <= high:
        middle = (low + high) // 2
        if time_values[middle] <= target_time_ms:
            result = middle
            low = middle + 1
        else:
            high = middle - 1
    return result if result >= 0 else 0


def _get_compass_direction_label(heading_degrees: float) -> str:
    normalized_heading = ((heading_degrees % 360) + 360) % 360
    if 45 <= normalized_heading < 135:
        return "E"
    if 135 <= normalized_heading < 225:
        return "S"
    if 225 <= normalized_heading < 315:
        return "W"
    return "N"


def _scale_stage_pixels(base_pixels: float, frame_width: int | float) -> int:
    return max(0, int(round(base_pixels * (float(frame_width) / BASE_RENDER_WIDTH))))


def _split_even_slot_widths(total_width: int) -> tuple[int, int]:
    left_width = max(0, total_width // 2)
    right_width = max(0, total_width - left_width)
    left_width -= left_width % 2
    right_width -= right_width % 2

    remaining_width = max(0, total_width - left_width - right_width)
    if remaining_width >= 2:
        right_width += remaining_width - (remaining_width % 2)

    return left_width, right_width


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    message = stderr or stdout or "ffmpeg failed"
    raise RuntimeError(message)


def _normalize_view(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    raw_layout = payload.get("layout")
    raw_camera_key = payload.get("cameraKey")
    if raw_layout not in PLAYER_LAYOUT_OPTIONS:
        return None
    if not isinstance(raw_camera_key, str) or raw_camera_key not in CAMERA_ORDER:
        return None
    return {"layout": raw_layout, "cameraKey": raw_camera_key}


def _normalize_export_format(value: object) -> str:
    return "hd" if value == "hd" else "4k"


def _coerce_nonnegative_float(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        return None
    return max(0.0, numeric_value)


def _round_time(value: float) -> float:
    return round(value, 3)


def _split_clip_stem(stem: str) -> tuple[str, str]:
    normalized_stem = stem.lower()
    for camera_key in CAMERA_ORDER:
        suffix = f"-{camera_key}"
        if normalized_stem.endswith(suffix):
            return normalized_stem[: -len(suffix)], camera_key
    return normalized_stem, "unknown"


def _infer_event_timestamp(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None