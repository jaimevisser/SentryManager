from __future__ import annotations

import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

frontend_app_module = importlib.import_module("app.frontend.app")


class FrontendAppTests(unittest.TestCase):
    def test_create_app_starts_background_workers(self) -> None:
        with mock.patch.object(frontend_app_module, "start_event_processing_worker") as indexing_mock:
            with mock.patch.object(frontend_app_module, "start_render_worker_thread") as render_mock:
                app = frontend_app_module.create_app()

        self.assertIsNotNone(app)
        indexing_mock.assert_called_once_with()
        render_mock.assert_called_once()

    def test_index_queues_discovered_event_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            (event_dir / "2026-03-31_06-42-49-front.mp4").write_bytes(b"")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "queue_discovered_event_processing") as queue_mock:
                    response = app.test_client().get("/")
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        queue_mock.assert_called_once()
        self.assertEqual([event_dir], queue_mock.call_args.args[0])

    def test_player_edits_wait_for_background_indexing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            (event_dir / "2026-03-31_06-42-49-front.mp4").write_bytes(b"")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "queue_event_processing") as queue_mock:
                    response = app.test_client().post(
                        "/events/SavedClips/2026-03-31_06-53-21/player-edits",
                        json={
                            "trimStartTime": 0,
                            "trimEndTime": 1,
                            "exportFormat": "hd",
                            "startMarkerView": {"layout": "single", "cameraKey": "front"},
                            "cameraMarkers": [],
                        },
                    )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(409, response.status_code)
        queue_mock.assert_called_once_with(event_dir)
        self.assertFalse((event_dir / "sentrymanager.json").exists())


if __name__ == "__main__":
    unittest.main()