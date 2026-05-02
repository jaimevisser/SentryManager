from __future__ import annotations

import os
from pathlib import Path
import threading
import time

from .jobs import claim_next_queued_job, mark_render_job_failed, mark_render_job_succeeded, persist_latest_render_metadata
from .pipeline import render_event


_RENDER_WORKER_THREAD: threading.Thread | None = None
_RENDER_WORKER_LOCK = threading.Lock()


def process_next_render_job(footage_root: Path) -> bool:
    job = claim_next_queued_job(footage_root)
    if job is None:
        return False

    event_id = str(job.get("eventId") or "")
    event_dir = (footage_root / event_id).resolve()
    if not event_id or not event_dir.is_dir():
        mark_render_job_failed(footage_root, str(job.get("id") or ""), "Clip folder not found.")
        return True

    player_edits = job.get("playerEdits")
    output_profile = job.get("outputProfile")
    try:
        render_metadata = render_event(
            event_dir=event_dir,
            footage_root=footage_root,
            event_id=event_id,
            player_edits=player_edits if isinstance(player_edits, dict) else None,
            output_profile=output_profile if isinstance(output_profile, str) else None,
        )
        mark_render_job_succeeded(footage_root, str(job.get("id") or ""), render_metadata)
        persist_latest_render_metadata(event_dir, render_metadata)
    except Exception as error:  # noqa: BLE001 - worker should report job failures and continue
        mark_render_job_failed(footage_root, str(job.get("id") or ""), str(error))

    return True


def run_render_worker_loop(footage_root: Path, poll_interval_seconds: float) -> None:
    while True:
        if process_next_render_job(footage_root):
            continue
        time.sleep(poll_interval_seconds)


def start_render_worker_thread(
    footage_root: Path | None = None,
    poll_interval_seconds: float | None = None,
) -> threading.Thread | None:
    if os.getenv("RENDER_WORKER_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return None

    resolved_footage_root = (footage_root or Path(os.getenv("TESLACAM_ROOT", "/data/TeslaCam"))).resolve()
    resolved_poll_interval = poll_interval_seconds if poll_interval_seconds is not None else float(
        os.getenv("RENDER_WORKER_POLL_INTERVAL_SECONDS", "1.0")
    )

    global _RENDER_WORKER_THREAD
    with _RENDER_WORKER_LOCK:
        if _RENDER_WORKER_THREAD is not None and _RENDER_WORKER_THREAD.is_alive():
            return _RENDER_WORKER_THREAD

        _RENDER_WORKER_THREAD = threading.Thread(
            target=run_render_worker_loop,
            args=(resolved_footage_root, resolved_poll_interval),
            name="render-worker",
            daemon=True,
        )
        _RENDER_WORKER_THREAD.start()
        return _RENDER_WORKER_THREAD


def main() -> None:
    footage_root = Path(os.getenv("TESLACAM_ROOT", "/data/TeslaCam")).resolve()
    poll_interval_seconds = float(os.getenv("RENDER_WORKER_POLL_INTERVAL_SECONDS", "1.0"))
    run_render_worker_loop(footage_root, poll_interval_seconds)


if __name__ == "__main__":
    main()