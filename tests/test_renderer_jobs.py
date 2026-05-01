from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.renderer.jobs import (
    ACTIVE_JOB_STATUSES,
    claim_next_queued_job,
    enqueue_render_job,
    get_latest_event_render_job,
    get_render_job,
    mark_render_job_succeeded,
)


class RendererJobTests(unittest.TestCase):
    def test_job_queue_claim_and_success_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            footage_root.mkdir(parents=True)

            queued_job = enqueue_render_job(
                footage_root=footage_root,
                event_id="SavedClips/example",
                player_edits={
                    "trimStartTime": 1.0,
                    "trimEndTime": 2.0,
                    "exportFormat": "hd",
                    "startMarkerView": {"layout": "single", "cameraKey": "front"},
                    "cameraMarkers": [],
                },
                output_profile="hd",
            )

            latest_active_job = get_latest_event_render_job(
                footage_root,
                "SavedClips/example",
                statuses=ACTIVE_JOB_STATUSES,
            )
            self.assertIsNotNone(latest_active_job)
            self.assertEqual(queued_job["id"], latest_active_job["id"])
            self.assertEqual("queued", latest_active_job["status"])

            claimed_job = claim_next_queued_job(footage_root)
            self.assertIsNotNone(claimed_job)
            self.assertEqual(queued_job["id"], claimed_job["id"])
            self.assertEqual("running", claimed_job["status"])

            render_metadata = {
                "outputPath": "/data/TeslaCam/SavedClips/example/exports/example.mp4",
                "renderPlanPath": "/data/TeslaCam/SavedClips/example/exports/example.render-plan.json",
                "downloadFileName": "example.mp4",
            }
            completed_job = mark_render_job_succeeded(footage_root, queued_job["id"], render_metadata)
            self.assertIsNotNone(completed_job)
            self.assertEqual("succeeded", completed_job["status"])
            self.assertEqual(render_metadata["outputPath"], completed_job["outputPath"])
            self.assertEqual(render_metadata, completed_job["render"])

            stored_job = get_render_job(footage_root, queued_job["id"])
            self.assertIsNotNone(stored_job)
            self.assertEqual("succeeded", stored_job["status"])
            self.assertEqual(render_metadata, stored_job["render"])


if __name__ == "__main__":
    unittest.main()