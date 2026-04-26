from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from flask import Flask, abort, render_template, send_file, url_for

from .config import apply_settings


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


@dataclass
class EventSummary:
    name: str
    path: str
    category: str
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
        return send_file(thumbnail_path)

    @app.route("/event-clips/<path:clip_path>")
    def event_clip(clip_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        clip_file = (footage_root / clip_path).resolve()
        if not clip_file.is_file():
            abort(404)
        if not _is_within_root(clip_file, footage_root):
            abort(404)
        return send_file(clip_file, conditional=True)

    @app.route("/events/<path:event_path>")
    def event_player(event_path: str):
        footage_root = Path(app.config["TESLACAM_ROOT"]).resolve()
        event_dir = (footage_root / event_path).resolve()
        if not event_dir.is_dir():
            abort(404)
        if not _is_within_root(event_dir, footage_root):
            abort(404)

        event_summary = summarize_event_dir(event_dir, footage_root)
        if event_summary is None:
            abort(404)

        camera_playlists = build_camera_playlists_payload(event_dir, footage_root)
        if not camera_playlists:
            abort(404)

        default_view_key = "front" if "front" in camera_playlists else next(iter(camera_playlists))
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
                    }
                    for clip in clips
                ]
                for camera_key, clips in camera_playlists.items()
            },
            event_marker_time=event_summary.trigger_offset_seconds,
            page_title=f"{event_summary.day_label} Player | SentryManager",
            page_description=f"Review TeslaCam clips for {event_summary.name}.",
            page_shell_class="page-shell-full",
        )

    @app.route("/")
    def index() -> str:
        footage_root = Path(app.config["TESLACAM_ROOT"])
        event_summaries = discover_event_summaries(footage_root)
        day_groups = group_events_by_day(event_summaries)
        camera_counts = Counter(camera for event in event_summaries for camera in event.cameras)
        total_clips = sum(event.clip_count for event in event_summaries)
        return render_template(
            "index.html",
            footage_root=str(footage_root),
            footage_root_exists=footage_root.exists(),
            day_groups=day_groups,
            event_count=len(event_summaries),
            total_clips=total_clips,
            camera_counts=dict(camera_counts),
        )

    return app


def discover_event_summaries(footage_root: Path, limit: int | None = None) -> list[EventSummary]:
    if not footage_root.exists() or not footage_root.is_dir():
        return []

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
        if limit is not None and len(summaries) >= limit:
            break

    return sorted(summaries, key=lambda event: event.timestamp or datetime.min, reverse=True)


def summarize_event_dir(event_dir: Path, footage_root: Path) -> EventSummary | None:
    clip_files = sorted(event_dir.glob("*.mp4"))
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
    location_label = load_event_location_label(event_dir)
    trigger_offset_seconds = load_event_trigger_offset_seconds(event_dir, first_segment_timestamp)
    return EventSummary(
        name=event_dir.name if event_dir != footage_root else footage_root.name,
        path=str(relative_path),
        category=category,
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
    return selector


def load_event_location_label(event_dir: Path) -> str | None:
    event_file = event_dir / "event.json"
    if not event_file.is_file():
        return None

    try:
        payload = json.loads(event_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    street = payload.get("street")
    city = payload.get("city")
    location_parts = [value.strip() for value in (street, city) if isinstance(value, str) and value.strip()]
    if not location_parts:
        return None
    return ", ".join(location_parts)


def load_event_trigger_offset_seconds(event_dir: Path, first_segment_timestamp: datetime | None) -> float | None:
    if first_segment_timestamp is None:
        return None

    event_file = event_dir / "event.json"
    if not event_file.is_file():
        return None

    try:
        payload = json.loads(event_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    raw_timestamp = payload.get("timestamp")
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return None

    try:
        trigger_timestamp = datetime.fromisoformat(raw_timestamp.strip())
    except ValueError:
        return None

    return max(0.0, (trigger_timestamp - first_segment_timestamp).total_seconds())


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
