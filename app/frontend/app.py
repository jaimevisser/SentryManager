from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import shutil

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for

from ..config import apply_settings
from ..renderer import (
    ACTIVE_JOB_STATUSES,
    enqueue_render_job,
    get_latest_event_render_job,
    get_latest_render_metadata,
    get_normalized_edit_segments,
    get_render_job,
)
from ..sei import ensure_sei_sidecars, get_event_processing_marker_path, get_segment_sei_sidecar_path


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

SENTRY_EVENT_CAMERA_MAP = {
    "0": "front",
    "3": "left_repeater",
    "4": "right_repeater",
    "5": "left_pillar",
    "6": "right_pillar",
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


def create_app() -> Flask:
    app = Flask(__name__)
    apply_settings(app)

    @app.route("/event-thumbnails/<path:event_path>")
    def event_thumbnail(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        thumbnail_path = (footage_root / event_path / "thumb.png").resolve()
        if not thumbnail_path.is_file():
            abort(404)
        if not _is_within_root(thumbnail_path, footage_root):
            abort(404)
        return send_file(thumbnail_path, conditional=True, max_age=3600)

    @app.route("/event-clips/<path:clip_path>")
    def event_clip(clip_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        clip_file = (footage_root / clip_path).resolve()
        if not clip_file.is_file():
            abort(404)
        if not _is_within_root(clip_file, footage_root):
            abort(404)
        return send_file(clip_file, conditional=True)

    @app.route("/event-telemetry/<path:event_path>/<segment_key>")
    def event_telemetry(event_path: str, segment_key: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir():
            abort(404)
        if not _is_within_root(event_dir, footage_root):
            abort(404)

        sidecar_file = get_segment_sei_sidecar_path(event_dir, segment_key)
        if not sidecar_file.is_file():
            abort(404)
        if not _is_within_root(sidecar_file, footage_root):
            abort(404)

        return send_file(sidecar_file, mimetype="application/octet-stream", conditional=True)

    @app.route("/events/<path:event_path>")
    def event_player(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir():
            abort(404)
        if not _is_within_root(event_dir, footage_root):
            abort(404)

        clip_files = get_event_clip_files(event_dir)
        if not clip_files:
            abort(404)

        ensure_sei_sidecars(clip_files)

        event_summary = summarize_event_dir(event_dir, footage_root, clip_files=clip_files)
        if event_summary is None:
            abort(404)

        camera_playlists = build_camera_playlists_payload(event_dir, footage_root)
        if not camera_playlists:
            abort(404)

        default_view_key = get_default_player_view_key(event_summary, event_dir, camera_playlists)
        event_processing_state = load_event_processing_state(event_dir)
        event_fsd_on_percent = get_event_fsd_on_percent(event_processing_state)
        saved_player_edits = get_saved_player_edits(event_processing_state)
        normalized_edit_segments = get_normalized_edit_segments(event_summary.path, saved_player_edits)
        if event_processing_state.get("normalizedEditSegments") != normalized_edit_segments:
            event_processing_state["normalizedEditSegments"] = normalized_edit_segments
            try:
                write_event_processing_state(event_dir, event_processing_state)
            except OSError:
                pass
        latest_render = get_latest_render_metadata(event_dir)
        active_render_job = get_latest_event_render_job(footage_root, event_summary.path, statuses=ACTIVE_JOB_STATUSES)
        initial_start_time = get_initial_player_start_time(event_summary, saved_player_edits)
        return render_template(
            "event_player.html",
            event=event_summary,
            view_selector=build_view_selector(camera_playlists),
            default_view_key=default_view_key,
            playlist_payload={
                camera_key: [
                    {
                        "segmentKey": clip.segment_key,
                        "segmentLabel": clip.segment_label,
                        "fileName": clip.file_name,
                        "url": url_for("event_clip", clip_path=clip.file_path),
                        "hasTelemetry": get_segment_sei_sidecar_path(event_dir, clip.segment_key).is_file(),
                        "telemetryUrl": url_for("event_telemetry", event_path=event_summary.path, segment_key=clip.segment_key),
                    }
                    for clip in clips
                ]
                for camera_key, clips in camera_playlists.items()
            },
            event_has_autopilot_activity=event_processing_state.get("hasAutopilotActivity", False),
            event_has_steering_angle_data=event_processing_state.get("hasSteeringAngleData", False),
            event_fsd_on_percent=event_fsd_on_percent,
            event_marker_time=event_summary.trigger_offset_seconds if event_summary.category == "SentryClips" else None,
            initial_start_time=initial_start_time,
            saved_player_edits=saved_player_edits,
            normalized_edit_segments=normalized_edit_segments,
            player_edits_save_url=url_for("update_event_player_edits", event_path=event_summary.path),
            player_render_url=url_for("render_event_export", event_path=event_summary.path),
            player_download_url=url_for("download_latest_event_render", event_path=event_summary.path),
            active_render_job=serialize_render_job(event_summary.path, active_render_job) if active_render_job else None,
            latest_render=latest_render,
            page_delete_event_path=event_summary.path,
            page_delete_redirect_url=url_for("index"),
            page_title=f"{event_summary.day_label} Player | SentryManager",
            page_description=f"Review TeslaCam clips for {event_summary.name}.",
            page_shell_class="page-shell-full",
        )

    @app.route("/")
    def index() -> str:
        footage_root = Path(app.config["TESLACAM_ROOT"])
        event_summaries = discover_event_summaries(footage_root)
        day_groups = group_events_by_day(event_summaries)
        return render_template("index.html", day_groups=day_groups)

    @app.post("/events/delete")
    def delete_events():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid delete request."}), 400

        raw_event_paths = payload.get("eventPaths")
        if not isinstance(raw_event_paths, list) or len(raw_event_paths) == 0:
            return jsonify({"error": "Select at least one clip to delete."}), 400

        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_directories: list[Path] = []
        deleted_paths: list[str] = []
        seen_directories: set[Path] = set()

        for raw_event_path in raw_event_paths:
            if not isinstance(raw_event_path, str) or not raw_event_path.strip():
                return jsonify({"error": "Invalid clip selection."}), 400

            normalized_event_path = Path(raw_event_path.strip())
            if normalized_event_path in {Path("."), Path("")}:
                return jsonify({"error": "Deleting the TeslaCam root is not allowed."}), 400

            event_dir = (footage_root / normalized_event_path).resolve()
            if not event_dir.is_dir() or not _is_within_root(event_dir, footage_root):
                return jsonify({"error": f"Clip folder not found: {raw_event_path}"}), 404

            if event_dir in seen_directories:
                continue

            seen_directories.add(event_dir)
            event_directories.append(event_dir)
            deleted_paths.append(str(normalized_event_path))

        for event_dir in event_directories:
            try:
                shutil.rmtree(event_dir)
            except OSError:
                return jsonify({"error": f"Could not delete {event_dir.name}."}), 500

        _EVENT_SUMMARY_CACHE.clear()
        return jsonify({"deletedPaths": deleted_paths})

    @app.post("/events/<path:event_path>/player-edits")
    def update_event_player_edits(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir() or not _is_within_root(event_dir, footage_root):
            return jsonify({"error": "Clip folder not found."}), 404

        payload = request.get_json(silent=True)
        player_edits = normalize_saved_player_edits(payload)
        if player_edits is None:
            return jsonify({"error": "Invalid player edits request."}), 400

        processing_state = load_event_processing_state(event_dir)
        processing_state["playerEdits"] = player_edits
        processing_state["normalizedEditSegments"] = get_normalized_edit_segments(event_path, player_edits)
        try:
            write_event_processing_state(event_dir, processing_state)
        except OSError:
            return jsonify({"error": "Could not save player edits."}), 500

        return jsonify({
            "playerEdits": player_edits,
            "normalizedEditSegments": processing_state["normalizedEditSegments"],
        })

    @app.post("/events/<path:event_path>/render")
    def render_event_export(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir() or not _is_within_root(event_dir, footage_root):
            return jsonify({"error": "Clip folder not found."}), 404

        processing_state = load_event_processing_state(event_dir)
        payload = request.get_json(silent=True)
        requested_profile = None
        player_edits = None
        if isinstance(payload, dict):
            raw_profile = payload.get("outputProfile")
            if isinstance(raw_profile, str):
                requested_profile = raw_profile
            player_edits = normalize_saved_player_edits(payload.get("playerEdits"))

        if player_edits is None:
            player_edits = get_saved_player_edits(processing_state)
        if player_edits is None:
            return jsonify({"error": "No saved player edits are available for export yet."}), 400

        processing_state["playerEdits"] = player_edits
        processing_state["normalizedEditSegments"] = get_normalized_edit_segments(event_path, player_edits)
        try:
            write_event_processing_state(event_dir, processing_state)
        except OSError:
            return jsonify({"error": "Could not save render request state."}), 500

        active_render_job = get_latest_event_render_job(footage_root, event_path, statuses=ACTIVE_JOB_STATUSES)
        if active_render_job is not None:
            return jsonify({"job": serialize_render_job(event_path, active_render_job)}), 202

        output_profile = requested_profile if isinstance(requested_profile, str) and requested_profile in EXPORT_FORMAT_OPTIONS else str(player_edits.get("exportFormat") or "4k")
        job = enqueue_render_job(
            footage_root=footage_root,
            event_id=event_path,
            player_edits=player_edits,
            output_profile=output_profile,
        )

        return jsonify({"job": serialize_render_job(event_path, job)}), 202

    @app.get("/events/<path:event_path>/render/jobs/<job_id>")
    def get_render_job_status(event_path: str, job_id: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        job = get_render_job(footage_root, job_id)
        if job is None or job.get("eventId") != event_path:
            return jsonify({"error": "Render job not found."}), 404
        return jsonify({"job": serialize_render_job(event_path, job)})

    @app.get("/events/<path:event_path>/render/latest")
    def download_latest_event_render(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir() or not _is_within_root(event_dir, footage_root):
            abort(404)

        latest_render = get_latest_render_metadata(event_dir)
        if latest_render is None:
            abort(404)

        output_path = Path(str(latest_render["outputPath"])).resolve()
        if not output_path.is_file() or not _is_within_root(output_path, footage_root):
            abort(404)

        return send_file(
            output_path,
            as_attachment=True,
            download_name=str(latest_render.get("downloadFileName") or output_path.name),
            conditional=True,
        )

    return app


def discover_event_summaries(footage_root: Path, limit: int | None = None) -> list[EventSummary]:
    if not footage_root.exists() or not footage_root.is_dir():
        return []

    event_directories = discover_event_directories(footage_root)
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


def get_event_fsd_on_percent(event_processing_state: dict[str, object]) -> float | None:
    raw_fsd_on_percent = event_processing_state.get("fsdOnPercent")
    if not isinstance(raw_fsd_on_percent, int | float):
        return None

    fsd_on_percent = float(raw_fsd_on_percent)
    if not math.isfinite(fsd_on_percent):
        return None

    return max(0.0, min(100.0, fsd_on_percent))


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
        return max(0.0, event.trigger_offset_seconds - 60.0)
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
