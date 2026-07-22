from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
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
from ..sei import (
    build_event_route_svg_from_event_dirs,
    calculate_combined_driver_assist_display,
    rebuild_event_route_svg_from_event_dirs,
    ensure_sei_sidecars,
    event_needs_processing_marker_backfill,
    event_needs_route_backfill,
    get_driver_assist_display_from_processing_state,
    get_event_route_svg_path,
    get_event_processing_marker_path,
    get_segment_route_svg_path,
    get_segment_sei_sidecar_path,
)
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
COMBINED_EVENT_KEY = "combinedEvent"
COMBINED_EVENT_MEMBERS_KEY = "memberClipNames"
COMBINED_EVENT_ROUTE_SVG_VERSION_KEY = "routeSvgVersion"
COMBINED_EVENT_ROUTE_SVG_VERSION = 1
COMBINED_INTO_KEY = "combinedIntoClipName"
EVENT_NOTES_FILE_NAME = "notes.txt"
EVENT_TIME_WINDOW_FILE_NAME = "event-window.json"
EVENT_TIME_WINDOW_CACHE_VERSION = 1
COMBINE_SEGMENT_SECONDS = 60.0
COMBINE_MARGIN_SECONDS = 1.0

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
    start_timestamp: datetime | None
    day_label: str
    time_label: str
    thumbnail_path: str | None
    location_label: str | None
    trigger_offset_seconds: float | None
    end_timestamp: datetime | None


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
    source_event_path: str


_EVENT_SUMMARY_CACHE: dict[
    tuple[str, tuple[tuple[str, int, int, int], ...]],
    list[EventSummary],
] = {}
_EVENT_CLIP_DURATION_CACHE: dict[tuple[str, int], float] = {}
_EVENT_INDEXING_QUEUE: queue.Queue[Path] = queue.Queue()
_EVENT_INDEXING_PENDING: set[Path] = set()
_EVENT_INDEXING_LOCK = threading.Lock()
_EVENT_INDEXING_THREAD: threading.Thread | None = None


def get_footage_root(app: Flask) -> Path:
    return Path(app.config["TESLACAM_ROOT"]).resolve()


def is_event_indexed(event_dir: Path) -> bool:
    return get_event_processing_marker_path(event_dir).is_file()


def event_processing_needs_refresh(event_dir: Path) -> bool:
    candidate_directories = get_combined_event_source_directories(event_dir)
    if event_dir not in candidate_directories:
        candidate_directories = [event_dir, *candidate_directories]

    for candidate_dir in candidate_directories:
        if not is_event_indexed(candidate_dir):
            return True
        if event_needs_route_backfill(candidate_dir) or event_needs_processing_marker_backfill(candidate_dir):
            return True

    return False


def refresh_event_processing_state(event_dir: Path) -> bool:
    if not is_event_indexed(event_dir):
        return False

    if not event_processing_needs_refresh(event_dir):
        return True

    clip_files = get_event_clip_files(event_dir)
    if not clip_files:
        return False

    try:
        ensure_sei_sidecars(clip_files)
    except (OSError, ValueError):
        return False

    _EVENT_SUMMARY_CACHE.clear()
    return True


def queue_event_processing(event_dir: Path) -> None:
    if is_event_indexed(event_dir) and not event_processing_needs_refresh(event_dir):
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
            if is_event_indexed(event_dir) and not event_processing_needs_refresh(event_dir):
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


def get_event_relative_path(event_dir: Path, footage_root: Path) -> str:
    return str(event_dir.relative_to(footage_root) if event_dir != footage_root else Path("."))


def get_direct_event_clip_files(event_dir: Path) -> list[Path]:
    return sorted(event_dir.glob("*.mp4"), key=lambda path: path.name.lower())


def _normalize_combined_member_names(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []

    raw_member_names = payload.get(COMBINED_EVENT_MEMBERS_KEY)
    if not isinstance(raw_member_names, list):
        return []

    member_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in raw_member_names:
        if not isinstance(raw_name, str):
            continue
        normalized_name = raw_name.strip()
        if not normalized_name or normalized_name in seen_names:
            continue
        if Path(normalized_name).name != normalized_name:
            continue
        seen_names.add(normalized_name)
        member_names.append(normalized_name)
    return member_names


def get_combined_event_member_names(processing_state: dict[str, object]) -> list[str]:
    return _normalize_combined_member_names(processing_state.get(COMBINED_EVENT_KEY))


def has_combined_event_members(processing_state: dict[str, object]) -> bool:
    return len(get_combined_event_member_names(processing_state)) > 0


def get_combined_event_route_svg_version(processing_state: dict[str, object]) -> int | None:
    combined_payload = processing_state.get(COMBINED_EVENT_KEY)
    if not isinstance(combined_payload, dict):
        return None

    raw_version = combined_payload.get(COMBINED_EVENT_ROUTE_SVG_VERSION_KEY)
    if isinstance(raw_version, int) and not isinstance(raw_version, bool):
        return raw_version
    return None


def maybe_backfill_combined_event_route_svg(event_dir: Path, event_processing_state: dict[str, object]) -> None:
    if not has_combined_event_members(event_processing_state):
        return

    route_svg_path = get_event_route_svg_path(event_dir)
    if route_svg_path.is_file() and get_combined_event_route_svg_version(event_processing_state) == COMBINED_EVENT_ROUTE_SVG_VERSION:
        return

    if rebuild_event_route_svg_from_event_dirs(event_dir, get_combined_event_directories(event_dir)):
        combined_payload = event_processing_state.get(COMBINED_EVENT_KEY)
        if isinstance(combined_payload, dict):
            combined_payload[COMBINED_EVENT_ROUTE_SVG_VERSION_KEY] = COMBINED_EVENT_ROUTE_SVG_VERSION
            write_event_processing_state(event_dir, event_processing_state)


def get_combined_owner_name(processing_state: dict[str, object]) -> str | None:
    raw_owner_name = processing_state.get(COMBINED_INTO_KEY)
    if not isinstance(raw_owner_name, str):
        return None

    normalized_owner_name = raw_owner_name.strip()
    if not normalized_owner_name or Path(normalized_owner_name).name != normalized_owner_name:
        return None
    return normalized_owner_name


def get_combined_owner_directory(event_dir: Path) -> Path | None:
    owner_name = get_combined_owner_name(load_event_processing_state(event_dir))
    if owner_name is None:
        return None

    owner_dir = event_dir.parent / owner_name
    if not owner_dir.is_dir():
        return None
    return owner_dir


def get_event_storage_directory(event_dir: Path) -> Path:
    combined_owner_dir = get_combined_owner_directory(event_dir)
    return combined_owner_dir if combined_owner_dir is not None else event_dir


def get_event_notes_path(event_dir: Path) -> Path:
    return get_event_storage_directory(event_dir) / EVENT_NOTES_FILE_NAME


def read_event_notes(event_dir: Path) -> str:
    notes_file = get_event_notes_path(event_dir)
    if not notes_file.is_file():
        return ""

    try:
        return notes_file.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_event_notes(event_dir: Path, notes: str) -> None:
    notes_file = get_event_notes_path(event_dir)
    if notes == "":
        if notes_file.exists():
            notes_file.unlink()
        return

    notes_file.write_text(notes, encoding="utf-8")


def get_combined_event_directories(event_dir: Path) -> list[Path]:
    processing_state = load_event_processing_state(event_dir)
    member_names = get_combined_event_member_names(processing_state)
    if not member_names:
        return [event_dir]

    event_directories = [event_dir]
    seen_directories = {event_dir.resolve()}
    for member_name in member_names:
        member_dir = event_dir.parent / member_name
        resolved_member_dir = member_dir.resolve()
        if resolved_member_dir in seen_directories or not member_dir.is_dir():
            continue
        seen_directories.add(resolved_member_dir)
        event_directories.append(member_dir)
    return event_directories


def get_combined_event_source_directories(event_dir: Path) -> list[Path]:
    source_directories = [source_event_dir for source_event_dir in get_combined_event_directories(event_dir) if get_direct_event_clip_files(source_event_dir)]
    if source_directories:
        return source_directories
    return [event_dir]


def get_event_clip_files(event_dir: Path) -> list[Path]:
    clip_files: list[Path] = []
    for clip_event_dir in get_combined_event_directories(event_dir):
        clip_files.extend(get_direct_event_clip_files(clip_event_dir))
    return sorted(clip_files, key=lambda path: path.name.lower())


def get_event_time_window_path(event_dir: Path) -> Path:
    return event_dir / EVENT_TIME_WINDOW_FILE_NAME


def get_event_segment_source_clips(clip_files: list[Path]) -> list[tuple[str, Path]]:
    segment_camera_files: dict[str, dict[str, Path]] = {}
    for clip_file in sorted(clip_files, key=lambda path: path.name.lower()):
        segment_key, camera_key = split_clip_stem(clip_file.stem)
        if camera_key == "unknown":
            continue
        segment_camera_files.setdefault(segment_key, {})[camera_key] = clip_file

    segment_source_clips: list[tuple[str, Path]] = []
    for segment_key in sorted(segment_camera_files):
        camera_files = segment_camera_files[segment_key]
        source_clip = camera_files.get("front")
        if source_clip is None:
            source_clip = next(iter(camera_files.values()), None)
        if source_clip is None:
            continue
        segment_source_clips.append((segment_key, source_clip))
    return segment_source_clips


def infer_event_time_window_from_clip_files(clip_files: list[Path]) -> tuple[datetime, datetime] | None:
    segment_timestamps = sorted({
        infer_event_timestamp(segment_key)
        for segment_key, _ in get_event_segment_source_clips(clip_files)
    })
    valid_segment_timestamps = [timestamp for timestamp in segment_timestamps if timestamp is not None]
    if not valid_segment_timestamps:
        return None

    window_start = valid_segment_timestamps[0]
    window_end = valid_segment_timestamps[-1] + timedelta(seconds=COMBINE_SEGMENT_SECONDS)
    return window_start, window_end


def read_cached_event_time_window(
    event_dir: Path,
    segment_source_clips: list[tuple[str, Path]],
) -> tuple[datetime, datetime] | None:
    cache_path = get_event_time_window_path(event_dir)
    if not cache_path.is_file() or not segment_source_clips:
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("version") != EVENT_TIME_WINDOW_CACHE_VERSION:
        return None

    first_segment_key = segment_source_clips[0][0]
    last_segment_key, last_clip = segment_source_clips[-1]
    if payload.get("firstSegmentKey") != first_segment_key:
        return None
    if payload.get("lastSegmentKey") != last_segment_key:
        return None
    if payload.get("lastClipFileName") != last_clip.name:
        return None
    if payload.get("lastClipMtimeNs") != get_path_mtime_ns(last_clip):
        return None

    raw_start_timestamp = payload.get("startTimestamp")
    raw_end_timestamp = payload.get("endTimestamp")
    if not isinstance(raw_start_timestamp, str) or not isinstance(raw_end_timestamp, str):
        return None

    try:
        start_timestamp = datetime.fromisoformat(raw_start_timestamp)
        end_timestamp = datetime.fromisoformat(raw_end_timestamp)
    except ValueError:
        return None

    if end_timestamp <= start_timestamp:
        return None
    return start_timestamp, end_timestamp


def write_cached_event_time_window(
    event_dir: Path,
    segment_source_clips: list[tuple[str, Path]],
    time_window: tuple[datetime, datetime],
) -> None:
    if not segment_source_clips:
        return

    last_segment_key, last_clip = segment_source_clips[-1]
    payload = {
        "version": EVENT_TIME_WINDOW_CACHE_VERSION,
        "firstSegmentKey": segment_source_clips[0][0],
        "lastSegmentKey": last_segment_key,
        "lastClipFileName": last_clip.name,
        "lastClipMtimeNs": get_path_mtime_ns(last_clip),
        "startTimestamp": time_window[0].isoformat(),
        "endTimestamp": time_window[1].isoformat(),
    }

    cache_path = get_event_time_window_path(event_dir)
    temp_path = cache_path.with_name(f"{cache_path.name}.tmp-{os.getpid()}")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(cache_path)


def infer_exact_event_time_window(
    event_dir: Path,
    clip_files: list[Path] | None = None,
) -> tuple[datetime, datetime] | None:
    clip_files = clip_files if clip_files is not None else get_direct_event_clip_files(event_dir)
    segment_source_clips = get_event_segment_source_clips(clip_files)
    if not segment_source_clips:
        return None

    approximate_window = infer_event_time_window_from_clip_files(clip_files)
    if approximate_window is None:
        return None

    cached_time_window = read_cached_event_time_window(event_dir, segment_source_clips)
    if cached_time_window is not None:
        return cached_time_window

    last_segment_key, last_clip = segment_source_clips[-1]
    last_segment_timestamp = infer_event_timestamp(last_segment_key)
    if last_segment_timestamp is None:
        return approximate_window

    duration_seconds = get_clip_duration_seconds(last_clip)
    if duration_seconds is None:
        return approximate_window

    exact_time_window = (
        approximate_window[0],
        last_segment_timestamp + timedelta(seconds=duration_seconds),
    )
    try:
        write_cached_event_time_window(event_dir, segment_source_clips, exact_time_window)
    except OSError:
        pass
    return exact_time_window


def infer_event_time_window(event_dir: Path) -> tuple[datetime, datetime] | None:
    return infer_event_time_window_from_clip_files(get_direct_event_clip_files(event_dir))


def infer_combined_event_time_window(
    event_dir: Path,
    *,
    exact: bool = False,
) -> tuple[datetime, datetime] | None:
    event_windows: list[tuple[datetime, datetime]] = []
    for source_event_dir in get_combined_event_directories(event_dir):
        event_window = infer_exact_event_time_window(source_event_dir) if exact else infer_event_time_window(source_event_dir)
        if event_window is None:
            continue
        event_windows.append(event_window)

    if not event_windows:
        return None

    return (
        min(window[0] for window in event_windows),
        max(window[1] for window in event_windows),
    )


def is_hidden_combined_event(event_dir: Path) -> bool:
    return get_combined_owner_name(load_event_processing_state(event_dir)) is not None


def expand_selected_event_directories(event_directories: list[Path]) -> list[Path]:
    expanded_directories: list[Path] = []
    seen_directories: set[Path] = set()
    for event_dir in event_directories:
        for resolved_event_dir in get_combined_event_directories(event_dir):
            if resolved_event_dir in seen_directories:
                continue
            seen_directories.add(resolved_event_dir)
            expanded_directories.append(resolved_event_dir)
    return expanded_directories


def is_saved_event_directory(event_dir: Path, footage_root: Path) -> bool:
    relative_path = event_dir.relative_to(footage_root) if event_dir != footage_root else Path(".")
    return len(relative_path.parts) > 1 and relative_path.parts[0] == "SavedClips"


def get_combinable_event_directories(
    footage_root: Path,
    event_directories: list[Path],
) -> tuple[Path, list[Path]] | tuple[None, str]:
    if len(event_directories) < 2:
        return None, "Select at least two clips to combine."

    for event_dir in event_directories:
        if get_combined_owner_name(load_event_processing_state(event_dir)) is not None:
            return None, "Combined child clips cannot be merged directly."
        if not is_saved_event_directory(event_dir, footage_root):
            return None, "Only Saved clips can be combined."

    expanded_directories = expand_selected_event_directories(event_directories)
    if len(expanded_directories) < 2:
        return None, "Select at least two clips to combine."

    category_parent = expanded_directories[0].parent
    event_windows: list[tuple[Path, datetime, datetime]] = []
    for event_dir in expanded_directories:
        if event_dir.parent != category_parent:
            return None, "Only consecutive clips from the same SavedClips folder can be combined."
        event_window = infer_exact_event_time_window(event_dir)
        if event_window is None:
            return None, f"Could not read clip timing for {event_dir.name}."
        event_windows.append((event_dir, event_window[0], event_window[1]))

    ordered_windows = sorted(event_windows, key=lambda item: item[1])
    for current_window, next_window in zip(ordered_windows, ordered_windows[1:]):
        gap_seconds = abs((next_window[1] - current_window[2]).total_seconds())
        if gap_seconds > COMBINE_MARGIN_SECONDS:
            return None, "Selected clips must be consecutive within one second."

    owner_dir = ordered_windows[0][0]
    ordered_directories = [event_dir for event_dir, _, _ in ordered_windows]
    return owner_dir, ordered_directories


def get_combine_selection_status(
    footage_root: Path,
    event_directories: list[Path],
) -> dict[str, object]:
    owner_dir, ordered_directories_or_error = get_combinable_event_directories(footage_root, event_directories)
    if owner_dir is None:
        return {
            "allowed": False,
            "error": str(ordered_directories_or_error),
        }

    ordered_directories = ordered_directories_or_error
    return {
        "allowed": True,
        "error": None,
        "ownerEventPath": str(owner_dir.relative_to(footage_root) if owner_dir != footage_root else Path(".")),
        "orderedEventPaths": [
            str(event_dir.relative_to(footage_root) if event_dir != footage_root else Path("."))
            for event_dir in ordered_directories
        ],
    }


def combine_event_directories(
    footage_root: Path,
    event_directories: list[Path],
) -> tuple[Path, list[Path]] | tuple[None, str]:
    owner_dir, ordered_directories_or_error = get_combinable_event_directories(footage_root, event_directories)
    if owner_dir is None:
        return None, ordered_directories_or_error

    ordered_directories = ordered_directories_or_error
    owner_processing_state = load_event_processing_state(owner_dir)
    owner_processing_state[COMBINED_EVENT_KEY] = {
        COMBINED_EVENT_MEMBERS_KEY: [event_dir.name for event_dir in ordered_directories if event_dir != owner_dir],
    }
    owner_processing_state.pop(COMBINED_INTO_KEY, None)
    owner_processing_state.pop("playerEdits", None)
    owner_processing_state.pop("normalizedEditSegments", None)
    owner_processing_state.pop("latestRender", None)

    for event_dir in ordered_directories:
        if event_dir == owner_dir:
            continue
        processing_state = load_event_processing_state(event_dir)
        processing_state.pop(COMBINED_EVENT_KEY, None)
        processing_state[COMBINED_INTO_KEY] = owner_dir.name
        processing_state.pop("playerEdits", None)
        processing_state.pop("normalizedEditSegments", None)
        processing_state.pop("latestRender", None)
        write_event_processing_state(event_dir, processing_state)

    if rebuild_event_route_svg_from_event_dirs(owner_dir, ordered_directories):
        combined_payload = owner_processing_state.get(COMBINED_EVENT_KEY)
        if isinstance(combined_payload, dict):
            combined_payload[COMBINED_EVENT_ROUTE_SVG_VERSION_KEY] = COMBINED_EVENT_ROUTE_SVG_VERSION
    write_event_processing_state(owner_dir, owner_processing_state)

    clear_event_summary_cache()
    return owner_dir, ordered_directories


def uncombine_event_directory(event_dir: Path) -> bool:
    owner_processing_state = load_event_processing_state(event_dir)
    member_names = get_combined_event_member_names(owner_processing_state)
    if not member_names:
        return False

    owner_processing_state.pop(COMBINED_EVENT_KEY, None)
    owner_processing_state.pop("playerEdits", None)
    owner_processing_state.pop("normalizedEditSegments", None)
    owner_processing_state.pop("latestRender", None)
    write_event_processing_state(event_dir, owner_processing_state)
    rebuild_event_route_svg_from_event_dirs(event_dir, [event_dir])

    for member_name in member_names:
        member_dir = event_dir.parent / member_name
        if not member_dir.is_dir():
            continue
        member_processing_state = load_event_processing_state(member_dir)
        member_processing_state.pop(COMBINED_INTO_KEY, None)
        member_processing_state.pop("playerEdits", None)
        member_processing_state.pop("normalizedEditSegments", None)
        member_processing_state.pop("latestRender", None)
        write_event_processing_state(member_dir, member_processing_state)

    clear_event_summary_cache()
    return True


def get_delete_target_directories(event_directories: list[Path]) -> list[Path]:
    return expand_selected_event_directories(event_directories)


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


def build_event_route_svg_content(
    event_dir: Path,
    trim_start_time: float | None = None,
    trim_end_time: float | None = None,
    *,
    mode: str = "highlight",
) -> str | None:
    route_mode = mode if mode in {"highlight", "selected-only"} else "highlight"
    return build_event_route_svg_from_event_dirs(
        get_combined_event_directories(event_dir),
        trim_start_time=trim_start_time,
        trim_end_time=trim_end_time,
        mode=route_mode,
    )


def build_playlist_payload(
    event_dir: Path,
    event_path: str,
    footage_root: Path,
    camera_playlists: dict[str, list[EventClip]],
) -> dict[str, list[dict[str, object]]]:
    return {
        camera_key: [
            {
                "segmentKey": clip.segment_key,
                "segmentLabel": clip.segment_label,
                "fileName": clip.file_name,
                "url": url_for("event_clip", clip_path=clip.file_path),
                "duration": get_clip_duration_seconds(resolve_path_within_footage_root(footage_root, clip.file_path)) or 0,
                "hasTelemetry": get_segment_sei_sidecar_path(resolve_path_within_footage_root(footage_root, clip.source_event_path), clip.segment_key).is_file(),
                "telemetryUrl": url_for("event_telemetry", event_path=clip.source_event_path, segment_key=clip.segment_key),
                "hasRouteSvg": get_segment_route_svg_path(resolve_path_within_footage_root(footage_root, clip.source_event_path), clip.segment_key).is_file(),
                "routeSvgUrl": url_for("event_route_svg", event_path=clip.source_event_path, segment_key=clip.segment_key),
            }
            for clip in clips
        ]
        for camera_key, clips in camera_playlists.items()
    }


def build_event_player_template_context(event_dir: Path, footage_root: Path) -> dict[str, object] | None:
    clip_files = get_event_clip_files(event_dir)
    if not clip_files:
        return None

    event_summary = summarize_event_dir(
        event_dir,
        footage_root,
        clip_files=clip_files,
        time_window=infer_combined_event_time_window(event_dir, exact=True),
    )
    if event_summary is None:
        return None

    camera_playlists = build_camera_playlists_payload(event_dir, footage_root)
    if not camera_playlists:
        return None

    default_view_key = get_default_player_view_key(event_summary, event_dir, camera_playlists)
    event_processing_state = load_event_processing_state(event_dir)
    has_combined_members = has_combined_event_members(event_processing_state)
    maybe_backfill_combined_event_route_svg(event_dir, event_processing_state)
    combined_processing_states = [load_event_processing_state(member_dir) for member_dir in get_combined_event_source_directories(event_dir)]
    event_driver_assist_display = calculate_combined_driver_assist_display(combined_processing_states)
    saved_player_edits = get_saved_player_edits(event_processing_state)
    event_notes = read_event_notes(event_dir)
    normalized_edit_segments = get_normalized_edit_segments(event_summary.path, saved_player_edits)
    persist_normalized_edit_segments(event_dir, event_processing_state, normalized_edit_segments)
    latest_render = get_latest_render_metadata(event_dir)
    active_render_job = get_latest_event_render_job(footage_root, event_summary.path, statuses=ACTIVE_JOB_STATUSES)
    overlay_date_label = event_summary.timestamp.strftime("%d-%m-%Y") if event_summary.timestamp else None
    overlay_time_label = event_summary.timestamp.strftime("%H:%M") if event_summary.timestamp else None
    event_timestamp_iso = event_summary.timestamp.isoformat() if event_summary.timestamp else None
    event_route_svg_url = None
    if get_event_route_svg_path(event_dir).is_file():
        event_route_svg_url = url_for("event_route_svg_combined", event_path=event_summary.path)

    return {
        "event": event_summary,
        "view_selector": build_view_selector(camera_playlists),
        "default_view_key": default_view_key,
        "playlist_payload": build_playlist_payload(event_dir, event_summary.path, footage_root, camera_playlists),
        "event_has_autopilot_activity": any(state.get("hasAutopilotActivity", False) for state in combined_processing_states),
        "event_has_steering_angle_data": any(state.get("hasSteeringAngleData", False) for state in combined_processing_states),
        "event_driver_assist_display": event_driver_assist_display,
        "event_marker_time": event_summary.trigger_offset_seconds if event_summary.category == "SentryClips" else None,
        "initial_start_time": get_initial_player_start_time(event_summary, saved_player_edits),
        "saved_player_edits": saved_player_edits,
        "event_notes": event_notes,
        "normalized_edit_segments": normalized_edit_segments,
        "player_edits_save_url": url_for("update_event_player_edits", event_path=event_summary.path),
        "player_render_url": url_for("render_event_export", event_path=event_summary.path),
        "player_download_url": url_for("download_latest_event_render", event_path=event_summary.path),
        "active_render_job": serialize_render_job(event_summary.path, active_render_job) if active_render_job else None,
        "latest_render": latest_render,
        "overlay_date_label": overlay_date_label,
        "overlay_time_label": overlay_time_label,
        "event_timestamp_iso": event_timestamp_iso,
        "event_route_svg_url": event_route_svg_url,
        "page_delete_event_path": event_summary.path,
        "page_delete_redirect_url": url_for("index"),
        "page_uncombine_event_path": event_summary.path if has_combined_members else None,
        "page_uncombine_redirect_url": url_for("index") if has_combined_members else None,
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
            if not is_hidden_combined_event(child):
                event_directories.append(child)
            continue
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and list(grandchild.glob("*.mp4")) and not is_hidden_combined_event(grandchild):
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


def summarize_event_dir(
    event_dir: Path,
    footage_root: Path,
    clip_files: list[Path] | None = None,
    time_window: tuple[datetime, datetime] | None = None,
) -> EventSummary | None:
    clip_files = clip_files if clip_files is not None else get_event_clip_files(event_dir)
    if not clip_files:
        return None

    cameras = sorted({infer_camera_name(path.name) for path in clip_files}, key=camera_sort_key)
    if time_window is None:
        time_window = infer_combined_event_time_window(event_dir)
    first_segment_timestamp = time_window[0] if time_window is not None else None
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
        start_timestamp=first_segment_timestamp,
        day_label=format_day_label(timestamp),
        time_label=format_time_label(timestamp),
        thumbnail_path=str(relative_path) if thumbnail_file.is_file() else None,
        location_label=location_label,
        trigger_offset_seconds=trigger_offset_seconds,
        end_timestamp=time_window[1] if time_window is not None else None,
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


def get_clip_duration_seconds(clip_file: Path) -> float | None:
    cache_key = (str(clip_file.resolve()), get_path_mtime_ns(clip_file))
    cached_duration = _EVENT_CLIP_DURATION_CACHE.get(cache_key)
    if cached_duration is not None:
        return cached_duration

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(clip_file),
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        duration_seconds = float(result.stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None

    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return None

    _EVENT_CLIP_DURATION_CACHE[cache_key] = duration_seconds
    return duration_seconds


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
    for clip_file in get_event_clip_files(event_dir):
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
                source_event_path=get_event_relative_path(clip_file.parent, footage_root),
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
    return get_driver_assist_display_from_processing_state(event_processing_state)


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


def normalize_event_notes(raw_notes: object) -> str | None:
    if not isinstance(raw_notes, str):
        return None

    return raw_notes.replace("\r\n", "\n").replace("\r", "\n")


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
