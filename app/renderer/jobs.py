from __future__ import annotations

from datetime import UTC, datetime
import json
import uuid
from pathlib import Path


JOB_ROOT_DIRNAME = ".sentrymanager/render-jobs"
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
ACTIVE_JOB_STATUSES = {"queued", "running"}


def enqueue_render_job(
    footage_root: Path,
    event_id: str,
    player_edits: dict[str, object],
    output_profile: str,
) -> dict[str, object]:
    job_root = _ensure_job_directories(footage_root)
    job_id = uuid.uuid4().hex
    requested_at = datetime.now(UTC).isoformat()
    job = {
        "id": job_id,
        "eventId": event_id,
        "status": "queued",
        "requestedAt": requested_at,
        "startedAt": None,
        "finishedAt": None,
        "outputProfile": output_profile,
        "playerEdits": player_edits,
        "renderPlanPath": None,
        "outputPath": None,
        "errorMessage": None,
        "progressMessage": "Queued...",
        "render": None,
    }
    _write_job_file(_status_dir(job_root, "queued") / f"{job_id}.json", job)
    return job


def get_render_job(footage_root: Path, job_id: str) -> dict[str, object] | None:
    job_path, _ = _find_job_path(footage_root, job_id)
    if job_path is None:
        return None
    return _read_job_file(job_path)


def get_latest_event_render_job(
    footage_root: Path,
    event_id: str,
    statuses: set[str] | None = None,
) -> dict[str, object] | None:
    matching_jobs: list[dict[str, object]] = []
    for job in iter_render_jobs(footage_root, statuses=statuses):
        if job.get("eventId") != event_id:
            continue
        matching_jobs.append(job)
    if not matching_jobs:
        return None
    matching_jobs.sort(key=lambda job: str(job.get("requestedAt") or ""), reverse=True)
    return matching_jobs[0]


def iter_render_jobs(footage_root: Path, statuses: set[str] | None = None) -> list[dict[str, object]]:
    job_root = _ensure_job_directories(footage_root)
    jobs: list[dict[str, object]] = []
    status_values = statuses if statuses is not None else set(JOB_STATUSES)
    for status in JOB_STATUSES:
        if status not in status_values:
            continue
        for job_path in sorted(_status_dir(job_root, status).glob("*.json")):
            job = _read_job_file(job_path)
            if job is not None:
                jobs.append(job)
    return jobs


def claim_next_queued_job(footage_root: Path) -> dict[str, object] | None:
    job_root = _ensure_job_directories(footage_root)
    queued_dir = _status_dir(job_root, "queued")
    running_dir = _status_dir(job_root, "running")
    queued_paths = sorted(queued_dir.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
    for queued_path in queued_paths:
        job = _read_job_file(queued_path)
        if job is None:
            continue
        job["status"] = "running"
        job["startedAt"] = datetime.now(UTC).isoformat()
        job["progressMessage"] = "Rendering..."
        running_path = running_dir / queued_path.name
        _write_job_file(running_path, job)
        try:
            queued_path.unlink()
        except FileNotFoundError:
            running_path.unlink(missing_ok=True)
            continue
        return job
    return None


def mark_render_job_succeeded(
    footage_root: Path,
    job_id: str,
    render_metadata: dict[str, object],
) -> dict[str, object] | None:
    return _transition_job(
        footage_root,
        job_id,
        next_status="succeeded",
        progress_message="Ready",
        render_metadata=render_metadata,
        error_message=None,
    )


def mark_render_job_failed(
    footage_root: Path,
    job_id: str,
    error_message: str,
) -> dict[str, object] | None:
    return _transition_job(
        footage_root,
        job_id,
        next_status="failed",
        progress_message=error_message,
        render_metadata=None,
        error_message=error_message,
    )


def persist_latest_render_metadata(event_dir: Path, render_metadata: dict[str, object]) -> None:
    processing_state_path = event_dir / "sentrymanager.json"
    processing_state: dict[str, object] = {}
    if processing_state_path.is_file():
        try:
            payload = json.loads(processing_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            processing_state = payload
    processing_state["latestRender"] = render_metadata
    processing_state_path.write_text(
        json.dumps(processing_state, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _transition_job(
    footage_root: Path,
    job_id: str,
    next_status: str,
    progress_message: str,
    render_metadata: dict[str, object] | None,
    error_message: str | None,
) -> dict[str, object] | None:
    job_path, current_status = _find_job_path(footage_root, job_id)
    if job_path is None or current_status is None:
        return None
    job = _read_job_file(job_path)
    if job is None:
        return None
    job["status"] = next_status
    job["finishedAt"] = datetime.now(UTC).isoformat()
    job["progressMessage"] = progress_message
    job["errorMessage"] = error_message
    job["render"] = render_metadata
    if render_metadata is not None:
        job["renderPlanPath"] = render_metadata.get("renderPlanPath")
        job["outputPath"] = render_metadata.get("outputPath")
    next_path = _status_dir(_ensure_job_directories(footage_root), next_status) / job_path.name
    _write_job_file(next_path, job)
    job_path.unlink(missing_ok=True)
    return job


def _ensure_job_directories(footage_root: Path) -> Path:
    job_root = (footage_root / JOB_ROOT_DIRNAME).resolve()
    job_root.mkdir(parents=True, exist_ok=True)
    for status in JOB_STATUSES:
        _status_dir(job_root, status).mkdir(parents=True, exist_ok=True)
    return job_root


def _find_job_path(footage_root: Path, job_id: str) -> tuple[Path | None, str | None]:
    job_root = _ensure_job_directories(footage_root)
    for status in JOB_STATUSES:
        candidate = _status_dir(job_root, status) / f"{job_id}.json"
        if candidate.is_file():
            return candidate, status
    return None, None


def _status_dir(job_root: Path, status: str) -> Path:
    return job_root / status


def _read_job_file(job_path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_job_file(job_path: Path, job: dict[str, object]) -> None:
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(
        json.dumps(job, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )