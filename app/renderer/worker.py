from __future__ import annotations

import os
from pathlib import Path
import time

from .jobs import claim_next_queued_job, mark_render_job_failed, mark_render_job_succeeded, persist_latest_render_metadata
from .pipeline import render_event


def main() -> None:
    footage_root = Path(os.getenv("TESLACAM_ROOT", "/data/TeslaCam")).resolve()
    poll_interval_seconds = float(os.getenv("RENDER_WORKER_POLL_INTERVAL_SECONDS", "1.0"))

    while True:
        job = claim_next_queued_job(footage_root)
        if job is None:
            time.sleep(poll_interval_seconds)
            continue

        event_id = str(job.get("eventId") or "")
        event_dir = (footage_root / event_id).resolve()
        if not event_id or not event_dir.is_dir():
            mark_render_job_failed(footage_root, str(job.get("id") or ""), "Clip folder not found.")
            continue

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


if __name__ == "__main__":
    main()