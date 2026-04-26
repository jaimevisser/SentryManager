from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, render_template

from .config import apply_settings


@dataclass
class EventSummary:
    name: str
    path: str
    clip_count: int
    cameras: list[str]


def create_app() -> Flask:
    app = Flask(__name__)
    apply_settings(app)

    @app.route("/")
    def index() -> str:
        footage_root = Path(app.config["TESLACAM_ROOT"])
        event_summaries = discover_event_summaries(footage_root)
        camera_counts = Counter(camera for event in event_summaries for camera in event.cameras)
        total_clips = sum(event.clip_count for event in event_summaries)
        return render_template(
            "index.html",
            footage_root=str(footage_root),
            footage_root_exists=footage_root.exists(),
            event_summaries=event_summaries,
            event_count=len(event_summaries),
            total_clips=total_clips,
            camera_counts=dict(camera_counts),
        )

    return app


def discover_event_summaries(footage_root: Path, limit: int = 6) -> list[EventSummary]:
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
        clip_files = sorted(event_dir.glob("*.mp4"))
        if not clip_files:
            continue
        cameras = sorted({infer_camera_name(path.name) for path in clip_files})
        relative_path = event_dir.relative_to(footage_root) if event_dir != footage_root else Path(".")
        summaries.append(
            EventSummary(
                name=event_dir.name if event_dir != footage_root else footage_root.name,
                path=str(relative_path),
                clip_count=len(clip_files),
                cameras=cameras,
            )
        )
        if len(summaries) >= limit:
            break

    return summaries


def infer_camera_name(filename: str) -> str:
    stem = Path(filename).stem.lower()
    for camera in ("front", "back", "left_repeater", "right_repeater"):
        if stem.endswith(camera):
            return camera.replace("_", " ")
    return "unknown"


app = create_app()
