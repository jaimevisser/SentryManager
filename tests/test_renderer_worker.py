from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.renderer.jobs import enqueue_render_job, get_render_job
from app.renderer.worker import process_next_render_job


class RendererWorkerTests(unittest.TestCase):
    def test_process_next_render_job_succeeds_in_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "example"
            event_dir.mkdir(parents=True)
            marker_path = event_dir / "sentrymanager.json"
            marker_path.write_text("{}", encoding="utf-8")

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

            render_metadata = {
                "outputPath": str(event_dir / "exports" / "example.mp4"),
                "renderPlanPath": str(event_dir / "exports" / "example.render-plan.json"),
                "downloadFileName": "example.mp4",
            }

            with patch("app.renderer.worker.render_event", return_value=render_metadata):
                processed = process_next_render_job(footage_root)

            self.assertTrue(processed)
            stored_job = get_render_job(footage_root, queued_job["id"])
            self.assertIsNotNone(stored_job)
            self.assertEqual("succeeded", stored_job["status"])
            self.assertEqual(render_metadata, stored_job["render"])

    def test_process_next_render_job_returns_false_without_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            footage_root.mkdir(parents=True)

            self.assertFalse(process_next_render_job(footage_root))


if __name__ == "__main__":
    unittest.main()