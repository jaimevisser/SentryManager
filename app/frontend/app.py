from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sys
import threading

from flask import Flask, abort, url_for

from ..renderer import (
    ACTIVE_JOB_STATUSES,
    enqueue_render_job,
    get_latest_event_render_job,
    get_latest_render_metadata,
    get_normalized_edit_segments,
    get_render_job,
    start_render_worker_thread,
)
from ..sei import ensure_sei_sidecars, get_event_processing_marker_path, get_segment_sei_sidecar_path
from .routes import register_routes


CAMERA_ORDER = (
    "front",
    "back",
    "left_repeater",
    "right_repeater",
    "left_pillar",
    "right_pillar",
)

CAMERA_LABELS = {
    "front": "Front",
    "back": "Back",
    "left_repeater": "Left repeater",
    "right_repeater": "Right repeater",
    "left_pillar": "Left pillar",
    "right_pillar": "Right pillar",
    "unknown": "Unknown",
}

PLAYER_LAYOUT_OPTIONS = {"single", "double", "triple"}
EXPORT_FORMAT_OPTIONS = {"4k", "hd"}
DEFAULT_SENTRY_PLAYER_PREROLL_SECONDS = 20.0

SENTRY_EVENT_CAMERA_MAP = {
    "0": "front",
    "3": "left_pillar",
    "4": "right_pillar",
    "5": "left_repeater",
    "6": "right_repeater",
    "7": "back",
}


@dataclass
class EventSummary:
    name: str
    path: str
    category: str
    category_label: str
    clip_count: int
    cameras: list[str]
    timestamp: datetime | None
    day_label: str
    time_label: str
    thumbnail_path: str | None
    location_label: str | None
    trigger_offset_seconds: float | None


@dataclass
class EventDayGroup:
    day_key: str
    day_label: str
    event_count: int
    events: list[EventSummary]


@dataclass
class EventClip:
    camera_key: str
    camera_label: str
    segment_key: str
    segment_label: str
    file_name: str
    file_path: str


_EVENT_SUMMARY_CACHE: dict[
    tuple[str, tuple[tuple[str, int, int, int], ...]],
    list[EventSummary],
] = {}
_EVENT_INDEXING_QUEUE: queue.Queue[Path] = queue.Queue()
_EVENT_INDEXING_PENDING: set[Path] = set()
_EVENT_INDEXING_LOCK = threading.Lock()
_EVENT_INDEXING_THREAD: threading.Thread | None = None


def get_footage_root(app: Flask) -> Path:
    return Path(app.config["TESLACAM_ROOT"]).resolve()


def is_event_indexed(event_dir: Path) -> bool:
    return get_event_processing_marker_path(event_dir).is_file()


def queue_event_processing(event_dir: Path) -> None:
    if is_event_indexed(event_dir):
        return

    with _EVENT_INDEXING_LOCK:
        if event_dir in _EVENT_INDEXING_PENDING:
            return
        _EVENT_INDEXING_PENDING.add(event_dir)

    _EVENT_INDEXING_QUEUE.put(event_dir)


def queue_discovered_event_processing(event_directories: list[Path]) -> None:
    for event_dir in event_directories:
        queue_event_processing(event_dir)


def _run_event_processing_worker() -> None:
    while True:
        event_dir = _EVENT_INDEXING_QUEUE.get()
        try:
            if is_event_indexed(event_dir):
                continue

            clip_files = get_event_clip_files(event_dir)
            if not clip_files:
                continue

            ensure_sei_sidecars(clip_files)
            _EVENT_SUMMARY_CACHE.clear()
        finally:
            with _EVENT_INDEXING_LOCK:
                _EVENT_INDEXING_PENDING.discard(event_dir)
            _EVENT_INDEXING_QUEUE.task_done()


def start_event_processing_worker() -> None:
    global _EVENT_INDEXING_THREAD

    with _EVENT_INDEXING_LOCK:
        if _EVENT_INDEXING_THREAD is not None and _EVENT_INDEXING_THREAD.is_alive():
            return

        _EVENT_INDEXING_THREAD = threading.Thread(
            target=_run_event_processing_worker,
            name="event-indexing-worker",
            daemon=True,
        )
        _EVENT_INDEXING_THREAD.start()


def resolve_path_within_footage_root(footage_root: Path, relative_path: str) -> Path:
    resolved_path = (footage_root / relative_path).resolve()
    if not _is_within_root(resolved_path, footage_root):
        abort(404)
    return resolved_path


def require_event_dir(footage_root: Path, event_path: str) -> Path:
    event_dir = resolve_path_within_footage_root(footage_root, event_path)
    if not event_dir.is_dir():
        abort(404)
    return event_dir


def require_file_path(footage_root: Path, relative_path: str) -> Path:
    file_path = resolve_path_within_footage_root(footage_root, relative_path)
    if not file_path.is_file():
        abort(404)
    return file_path


def persist_normalized_edit_segments(
    event_dir: Path,
    event_processing_state: dict[str, object],
    normalized_edit_segments: list[dict[str, object]],
) -> None:
    if not is_event_indexed(event_dir):
        return

    if event_processing_state.get("normalizedEditSegments") == normalized_edit_segments:
        return

    event_processing_state["normalizedEditSegments"] = normalized_edit_segments
    try:
        write_event_processing_state(event_dir, event_processing_state)
    except OSError:
        pass


def build_playlist_payload(
    event_dir: Path,
    event_path: str,
    camera_playlists: dict[str, list[EventClip]],
) -> dict[str, list[dict[str, object]]]:
    return {
        camera_key: [
            {
                "segmentKey": clip.segment_key,
                "segmentLabel": clip.segment_label,
                "fileName": clip.file_name,
                "url": url_for("event_clip", clip_path=clip.file_path),
                "hasTelemetry": get_segment_sei_sidecar_path(event_dir, clip.segment_key).is_file(),
                "telemetryUrl": url_for("event_telemetry", event_path=event_path, segment_key=clip.segment_key),
            }
            for clip in clips
        ]
        for camera_key, clips in camera_playlists.items()
    }


def build_event_player_template_context(event_dir: Path, footage_root: Path) -> dict[str, object] | None:
    clip_files = get_event_clip_files(event_dir)
    if not clip_files:
        return None

    event_summary = summarize_event_dir(event_dir, footage_root, clip_files=clip_files)
    if event_summary is None:
        return None

    camera_playlists = build_camera_playlists_payload(event_dir, footage_root)
    if not camera_playlists:
        return None

    default_view_key = get_default_player_view_key(event_summary, event_dir, camera_playlists)
    event_processing_state = load_event_processing_state(event_dir)
    event_driver_assist_display = get_event_driver_assist_display(event_processing_state)
    saved_player_edits = get_saved_player_edits(event_processing_state)
    normalized_edit_segments = get_normalized_edit_segments(event_summary.path, saved_player_edits)
    persist_normalized_edit_segments(event_dir, event_processing_state, normalized_edit_segments)
    latest_render = get_latest_render_metadata(event_dir)
    active_render_job = get_latest_event_render_job(footage_root, event_summary.path, statuses=ACTIVE_JOB_STATUSES)
    overlay_date_label = event_summary.timestamp.strftime("%d-%m-%Y") if event_summary.timestamp else None
    overlay_time_label = event_summary.timestamp.strftime("%H:%M") if event_summary.timestamp else None
    event_timestamp_iso = event_summary.timestamp.isoformat() if event_summary.timestamp else None

    return {
        "event": event_summary,
        "view_selector": build_view_selector(camera_playlists),
        "default_view_key": default_view_key,
        "playlist_payload": build_playlist_payload(event_dir, event_summary.path, camera_playlists),
        "event_has_autopilot_activity": event_processing_state.get("hasAutopilotActivity", False),
        "event_has_steering_angle_data": event_processing_state.get("hasSteeringAngleData", False),
        "event_driver_assist_display": event_driver_assist_display,
        "event_marker_time": event_summary.trigger_offset_seconds if event_summary.category == "SentryClips" else None,
        "initial_start_time": get_initial_player_start_time(event_summary, saved_player_edits),
        "saved_player_edits": saved_player_edits,
        "normalized_edit_segments": normalized_edit_segments,
        "player_edits_save_url": url_for("update_event_player_edits", event_path=event_summary.path),
        "player_render_url": url_for("render_event_export", event_path=event_summary.path),
        "player_download_url": url_for("download_latest_event_render", event_path=event_summary.path),
        "active_render_job": serialize_render_job(event_summary.path, active_render_job) if active_render_job else None,
        "latest_render": latest_render,
        "overlay_date_label": overlay_date_label,
        "overlay_time_label": overlay_time_label,
        "event_timestamp_iso": event_timestamp_iso,
        "page_delete_event_path": event_summary.path,
        "page_delete_redirect_url": url_for("index"),
        "page_title": f"{event_summary.day_label} Player | SentryManager",
        "page_description": f"Review TeslaCam clips for {event_summary.name}.",
        "page_shell_class": "page-shell-full",
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TESLACAM_ROOT"] = os.getenv("TESLACAM_ROOT", "/data/TeslaCam")
    start_event_processing_worker()
    start_render_worker_thread(get_footage_root(app))
    register_routes(app, sys.modules[__name__])
    return app


def clear_event_summary_cache() -> None:
    _EVENT_SUMMARY_CACHE.clear()


def discover_event_summaries(
    footage_root: Path,
    limit: int | None = None,
    event_directories: list[Path] | None = None,
) -> list[EventSummary]:
    if not footage_root.exists() or not footage_root.is_dir():
        return []

    event_directories = event_directories if event_directories is not None else discover_event_directories(footage_root)
    cache_key = build_event_summary_cache_key(footage_root.resolve(), event_directories)
    cached_summaries = _EVENT_SUMMARY_CACHE.get(cache_key)
    if cached_summaries is None:
        summaries: list[EventSummary] = []
        seen_paths: set[Path] = set()

        for event_dir in event_directories:
            if event_dir in seen_paths:
                continue
            seen_paths.add(event_dir)
            summary = summarize_event_dir(event_dir, footage_root)
            if summary is None:
                continue
            summaries.append(summary)

        cached_summaries = sorted(summaries, key=lambda event: event.timestamp or datetime.min, reverse=True)
        _EVENT_SUMMARY_CACHE.clear()
        _EVENT_SUMMARY_CACHE[cache_key] = cached_summaries

    if limit is None:
        return cached_summaries

    return cached_summaries[:limit]


def discover_event_directories(footage_root: Path) -> list[Path]:
    event_directories: list[Path] = []

    direct_mp4s = list(footage_root.glob("*.mp4"))
    if direct_mp4s:
        event_directories.append(footage_root)

    for child in sorted(footage_root.iterdir()):
        if not child.is_dir():
            continue
        if list(child.glob("*.mp4")):
            event_directories.append(child)
            continue
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and list(grandchild.glob("*.mp4")):
                event_directories.append(grandchild)

    return event_directories


def build_event_summary_cache_key(
    footage_root: Path,
    event_directories: list[Path],
) -> tuple[str, tuple[tuple[str, int, int, int], ...]]:
    return (
        str(footage_root),
        tuple(
            (
                str(event_dir.relative_to(footage_root) if event_dir != footage_root else Path(".")),
                get_path_mtime_ns(event_dir),
                get_path_mtime_ns(event_dir / "event.json"),
                get_path_mtime_ns(event_dir / "sentrymanager.json"),
                get_path_mtime_ns(event_dir / "thumb.png"),
            )
            for event_dir in event_directories
        ),
    )


def get_path_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def get_event_clip_files(event_dir: Path) -> list[Path]:
    return sorted(event_dir.glob("*.mp4"))


def summarize_event_dir(
    event_dir: Path,
    footage_root: Path,
    clip_files: list[Path] | None = None,
) -> EventSummary | None:
    clip_files = clip_files if clip_files is not None else get_event_clip_files(event_dir)
    if not clip_files:
        return None

    cameras = sorted({infer_camera_name(path.name) for path in clip_files}, key=camera_sort_key)
    segment_timestamps = [
        infer_event_timestamp(split_clip_stem(path.stem)[0])
        for path in clip_files
    ]
    first_segment_timestamp = min((timestamp for timestamp in segment_timestamps if timestamp is not None), default=None)
    relative_path = event_dir.relative_to(footage_root) if event_dir != footage_root else Path(".")
    timestamp = infer_event_timestamp(event_dir.name)
    category = relative_path.parts[0] if len(relative_path.parts) > 1 else "TeslaCam"
    thumbnail_file = event_dir / "thumb.png"
    event_payload = load_event_json_payload(event_dir)
    event_processing_state = load_event_processing_state(event_dir)
    category_label = load_event_category_label(event_processing_state, event_payload, category)
    location_label = extract_event_location_label(event_payload)
    trigger_offset_seconds = extract_event_trigger_offset_seconds(event_payload, first_segment_timestamp)
    return EventSummary(
        name=event_dir.name if event_dir != footage_root else footage_root.name,
        path=str(relative_path),
        category=category,
        category_label=category_label,
        clip_count=len(clip_files),
        cameras=cameras,
        timestamp=timestamp,
        day_label=format_day_label(timestamp),
        time_label=format_time_label(timestamp),
        thumbnail_path=str(relative_path) if thumbnail_file.is_file() else None,
        location_label=location_label,
        trigger_offset_seconds=trigger_offset_seconds,
    )


def group_events_by_day(events: list[EventSummary]) -> list[EventDayGroup]:
    grouped: dict[str, list[EventSummary]] = {}
    for event in events:
        day_key = event.timestamp.strftime("%Y-%m-%d") if event.timestamp else "unknown"
        grouped.setdefault(day_key, []).append(event)

    day_groups: list[EventDayGroup] = []
    for day_key, day_events in grouped.items():
        ordered_events = sorted(day_events, key=lambda event: event.timestamp or datetime.min, reverse=True)
        day_groups.append(
            EventDayGroup(
                day_key=day_key,
                day_label=ordered_events[0].day_label,
                event_count=len(ordered_events),
                events=ordered_events,
            )
        )

    return sorted(day_groups, key=lambda group: group.day_key, reverse=True)


def infer_event_timestamp(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def format_day_label(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "Unknown day"
    return timestamp.strftime("%A, %B %d")


def format_time_label(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "Unknown time"
    hour = timestamp.strftime("%I").lstrip("0") or "0"
    return f"{hour}{timestamp.strftime(':%M %p').lower()}"


def build_event_playlist(event_dir: Path, footage_root: Path, camera_key: str) -> list[EventClip]:
    playlist: list[EventClip] = []
    for clip_file in sorted(event_dir.glob("*.mp4")):
        segment_key, clip_camera_key = split_clip_stem(clip_file.stem)
        if clip_camera_key != camera_key:
            continue
        playlist.append(
            EventClip(
                camera_key=clip_camera_key,
                camera_label=format_camera_label(clip_camera_key),
                segment_key=segment_key,
                segment_label=format_segment_label(segment_key),
                file_name=clip_file.name,
                file_path=str(clip_file.relative_to(footage_root)),
            )
        )
    return playlist


def build_camera_playlists_payload(event_dir: Path, footage_root: Path) -> dict[str, list[EventClip]]:
    playlists: dict[str, list[EventClip]] = {}
    for camera_key in CAMERA_ORDER:
        playlist = build_event_playlist(event_dir, footage_root, camera_key)
        if playlist:
            playlists[camera_key] = playlist
    return playlists


def build_view_selector(camera_playlists: dict[str, list[EventClip]]) -> list[dict[str, str]]:
    selector = [
        {"key": camera_key, "label": format_camera_label(camera_key)}
        for camera_key in CAMERA_ORDER
        if camera_key in camera_playlists
    ]
    if {"back", "left_repeater", "right_repeater"}.issubset(camera_playlists):
        selector.append({"key": "full_rear", "label": "Full rear"})
    if {"front", "left_pillar", "right_pillar"}.issubset(camera_playlists):
        selector.append({"key": "full_front", "label": "Full front"})
    if {"left_repeater", "left_pillar"}.issubset(camera_playlists):
        selector.append({"key": "full_left", "label": "Full left"})
    if {"right_pillar", "right_repeater"}.issubset(camera_playlists):
        selector.append({"key": "full_right", "label": "Full right"})
    return selector


def get_default_player_view_key(
    event: EventSummary,
    event_dir: Path,
    camera_playlists: dict[str, list[EventClip]],
) -> str:
    if event.category == "SentryClips":
        trigger_camera_key = load_event_trigger_camera_key(event_dir)
        if trigger_camera_key in camera_playlists:
            return trigger_camera_key

    if "front" in camera_playlists:
        return "front"
    return next(iter(camera_playlists))


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


def extract_event_location_label(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None

    street = payload.get("street")
    city = payload.get("city")
    location_parts = [value.strip() for value in (street, city) if isinstance(value, str) and value.strip()]
    if not location_parts:
        return None
    return ", ".join(location_parts)


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


def fallback_event_category_label(category: str) -> str:
    if category == "SentryClips":
        return "Sentry"
    if category == "SavedClips":
        return "Saved"
    return category


def load_event_category_label(
    processing_state: dict[str, object],
    event_payload: dict[str, object] | None,
    category: str,
) -> str:
    marker_label = processing_state.get("eventCategoryLabel")
    if isinstance(marker_label, str) and marker_label.strip():
        return marker_label.strip()

    payload_label = extract_event_category_label(event_payload)
    if payload_label is not None:
        return payload_label

    return fallback_event_category_label(category)


def extract_event_trigger_offset_seconds(
    payload: dict[str, object] | None,
    first_segment_timestamp: datetime | None,
) -> float | None:
    if first_segment_timestamp is None:
        return None

    if payload is None:
        return None

    raw_timestamp = payload.get("timestamp")
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return None

    try:
        trigger_timestamp = datetime.fromisoformat(raw_timestamp.strip())
    except ValueError:
        return None

    return max(0.0, (trigger_timestamp - first_segment_timestamp).total_seconds())


def load_event_trigger_camera_key(event_dir: Path) -> str | None:
    payload = load_event_json_payload(event_dir)
    if payload is None:
        return None

    raw_camera = payload.get("camera")
    if raw_camera is None:
        return None

    return SENTRY_EVENT_CAMERA_MAP.get(str(raw_camera).strip())


def load_event_processing_state(event_dir: Path) -> dict[str, object]:
    marker_file = get_event_processing_marker_path(event_dir)
    if not marker_file.is_file():
        return {}

    try:
        payload = json.loads(marker_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload


def get_event_driver_assist_display(event_processing_state: dict[str, object]) -> dict[str, object] | None:
    raw_display = event_processing_state.get("driverAssistDisplay")
    if isinstance(raw_display, dict):
        raw_label = raw_display.get("label")
        raw_percent = raw_display.get("percent")
        raw_text = raw_display.get("text")
        if isinstance(raw_label, str) and raw_label in {"FSD", "AP"} and isinstance(raw_percent, int | float):
            percent = float(raw_percent)
            if math.isfinite(percent):
                clamped_percent = max(0.0, min(100.0, percent))
                return {
                    "label": raw_label,
                    "percent": clamped_percent,
                    "text": raw_text if isinstance(raw_text, str) and raw_text.strip() else f"{raw_label} {round(clamped_percent)}%",
                }

    raw_fsd_on_percent = event_processing_state.get("fsdOnPercent")
    if not isinstance(raw_fsd_on_percent, int | float):
        return None

    fsd_on_percent = float(raw_fsd_on_percent)
    if not math.isfinite(fsd_on_percent):
        return None

    clamped_percent = max(0.0, min(100.0, fsd_on_percent))
    return {
        "label": "FSD",
        "percent": clamped_percent,
        "text": f"FSD {round(clamped_percent)}%",
    }


def _coerce_nonnegative_number(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None

    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        return None

    return max(0.0, round(numeric_value, 3))


def normalize_player_view_selection(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None

    raw_layout = payload.get("layout")
    raw_camera_key = payload.get("cameraKey")
    if not isinstance(raw_layout, str) or raw_layout not in PLAYER_LAYOUT_OPTIONS:
        return None
    if not isinstance(raw_camera_key, str) or raw_camera_key not in CAMERA_ORDER:
        return None

    return {
        "layout": raw_layout,
        "cameraKey": raw_camera_key,
    }


def normalize_saved_player_edits(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None

    trim_start_time = _coerce_nonnegative_number(payload.get("trimStartTime"))
    trim_end_time = _coerce_nonnegative_number(payload.get("trimEndTime"))
    raw_export_format = payload.get("exportFormat", "4k")
    start_marker_view = normalize_player_view_selection(payload.get("startMarkerView"))
    raw_camera_markers = payload.get("cameraMarkers")
    if not isinstance(raw_export_format, str) or raw_export_format not in EXPORT_FORMAT_OPTIONS:
        return None
    if trim_start_time is None or trim_end_time is None or start_marker_view is None or not isinstance(raw_camera_markers, list):
        return None

    camera_markers: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for raw_marker in raw_camera_markers:
        if not isinstance(raw_marker, dict):
            return None

        raw_marker_id = raw_marker.get("id")
        if not isinstance(raw_marker_id, int) or isinstance(raw_marker_id, bool) or raw_marker_id < 1 or raw_marker_id in seen_ids:
            return None

        marker_time = _coerce_nonnegative_number(raw_marker.get("time"))
        marker_view = normalize_player_view_selection(raw_marker)
        if marker_time is None or marker_view is None:
            return None

        seen_ids.add(raw_marker_id)
        camera_markers.append({
            "id": raw_marker_id,
            "time": marker_time,
            "layout": marker_view["layout"],
            "cameraKey": marker_view["cameraKey"],
        })

    camera_markers.sort(key=lambda marker: (float(marker["time"]), int(marker["id"])))
    return {
        "trimStartTime": trim_start_time,
        "trimEndTime": trim_end_time,
        "exportFormat": raw_export_format,
        "startMarkerView": start_marker_view,
        "cameraMarkers": camera_markers,
    }


def get_saved_player_edits(event_processing_state: dict[str, object]) -> dict[str, object] | None:
    return normalize_saved_player_edits(event_processing_state.get("playerEdits"))


def get_sentry_player_preroll_seconds() -> float:
    raw_value = os.getenv("SENTRY_PLAYER_PREROLL_SECONDS")
    if raw_value is None:
        return DEFAULT_SENTRY_PLAYER_PREROLL_SECONDS

    try:
        parsed_value = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SENTRY_PLAYER_PREROLL_SECONDS

    if not math.isfinite(parsed_value) or parsed_value < 0:
        return DEFAULT_SENTRY_PLAYER_PREROLL_SECONDS

    return parsed_value


def serialize_render_job(event_path: str, job: dict[str, object]) -> dict[str, object]:
    serialized_job = dict(job)
    serialized_job["statusUrl"] = url_for("get_render_job_status", event_path=event_path, job_id=str(job.get("id") or ""))
    serialized_job["downloadUrl"] = url_for("download_latest_event_render", event_path=event_path)
    return serialized_job


def write_event_processing_state(event_dir: Path, processing_state: dict[str, object]) -> None:
    marker_file = get_event_processing_marker_path(event_dir)
    marker_file.write_text(
        json.dumps(processing_state, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


def get_initial_player_start_time(event: EventSummary, saved_player_edits: dict[str, object] | None = None) -> float:
    if isinstance(saved_player_edits, dict):
        raw_trim_start_time = saved_player_edits.get("trimStartTime")
        if isinstance(raw_trim_start_time, int | float) and not isinstance(raw_trim_start_time, bool):
            trim_start_time = float(raw_trim_start_time)
            if math.isfinite(trim_start_time) and trim_start_time > 0:
                return trim_start_time

    if event.category == "SentryClips" and event.trigger_offset_seconds is not None:
        return max(0.0, event.trigger_offset_seconds - get_sentry_player_preroll_seconds())
    return 0.0


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def infer_camera_name(filename: str) -> str:
    _, camera_key = split_clip_stem(Path(filename).stem)
    return format_camera_label(camera_key)


def split_clip_stem(stem: str) -> tuple[str, str]:
    normalized_stem = stem.lower()
    for camera_key in CAMERA_ORDER:
        suffix = f"-{camera_key}"
        if normalized_stem.endswith(suffix):
            return normalized_stem[: -len(suffix)], camera_key
    return normalized_stem, "unknown"


def format_camera_label(camera_key: str) -> str:
    return CAMERA_LABELS.get(camera_key, camera_key.replace("_", " ").title())


def camera_sort_key(camera_label: str) -> int:
    try:
        return list(CAMERA_LABELS.values()).index(camera_label)
    except ValueError:
        return len(CAMERA_LABELS)


def format_segment_label(segment_key: str) -> str:
    timestamp = infer_event_timestamp(segment_key)
    if timestamp is None:
        return segment_key
    return timestamp.strftime("%H:%M:%S")


app = create_app()
