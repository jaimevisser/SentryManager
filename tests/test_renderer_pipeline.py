from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.renderer.pipeline import build_render_plan, get_normalized_edit_segments


class RendererPipelineTests(unittest.TestCase):
    def test_normalizes_marker_state_into_contiguous_segments(self) -> None:
        player_edits = {
            "trimStartTime": 10.0,
            "trimEndTime": 40.0,
            "exportFormat": "hd",
            "startMarkerView": {"layout": "triple", "cameraKey": "front"},
            "cameraMarkers": [
                {"id": 1, "time": 20.0, "layout": "double", "cameraKey": "front"},
                {"id": 2, "time": 30.0, "layout": "single", "cameraKey": "back"},
            ],
        }

        segments = get_normalized_edit_segments("SavedClips/example", player_edits)

        self.assertEqual(3, len(segments))
        self.assertEqual(
            [
                {
                    "id": "seg-001",
                    "event_id": "SavedClips/example",
                    "timeline_start": 10.0,
                    "timeline_end": 20.0,
                    "layout": "triple",
                    "primary_camera": "front",
                    "visible_cameras": ["front", "left_pillar", "right_pillar"],
                    "export_format": "hd",
                    "label": None,
                    "notes": None,
                    "playback_rate": 1.0,
                },
                {
                    "id": "seg-002",
                    "event_id": "SavedClips/example",
                    "timeline_start": 20.0,
                    "timeline_end": 30.0,
                    "layout": "double",
                    "primary_camera": "front",
                    "visible_cameras": ["left_pillar", "front"],
                    "export_format": "hd",
                    "label": None,
                    "notes": None,
                    "playback_rate": 1.0,
                },
                {
                    "id": "seg-003",
                    "event_id": "SavedClips/example",
                    "timeline_start": 30.0,
                    "timeline_end": 40.0,
                    "layout": "single",
                    "primary_camera": "back",
                    "visible_cameras": ["back"],
                    "export_format": "hd",
                    "label": None,
                    "notes": None,
                    "playback_rate": 1.0,
                },
            ],
            segments,
        )

    def test_builds_render_plan_with_cross_clip_fragments_and_missing_camera_reporting(self) -> None:
        player_edits = {
            "trimStartTime": 2.0,
            "trimEndTime": 15.0,
            "exportFormat": "hd",
            "startMarkerView": {"layout": "double", "cameraKey": "front"},
            "cameraMarkers": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            event_dir.mkdir(parents=True)

            for file_name in (
                "2026-03-28_09-00-00-front.mp4",
                "2026-03-28_09-00-10-front.mp4",
                "2026-03-28_09-00-00-left_pillar.mp4",
            ):
                (event_dir / file_name).touch()

            with patch(
                "app.renderer.pipeline._probe_video",
                return_value={
                    "duration": 10.0,
                    "frame_rate": 30.0,
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                },
            ):
                render_plan = build_render_plan(
                    event_dir=event_dir,
                    footage_root=footage_root,
                    event_id="SavedClips/2026-03-28_09-12-13",
                    player_edits=player_edits,
                )

        self.assertEqual("hd", render_plan["outputProfile"])
        self.assertEqual({"width": 1920, "height": 1080}, render_plan["frameSize"])
        self.assertEqual(1, len(render_plan["segments"]))

        segment = render_plan["segments"][0]
        self.assertEqual("double", segment["layout"])
        self.assertEqual(2.0, segment["browserTimelineStart"])
        self.assertEqual(15.0, segment["browserTimelineEnd"])
        self.assertEqual(0.0, segment["renderTimelineStart"])
        self.assertEqual(13.0, segment["renderTimelineEnd"])
        self.assertEqual(["left_pillar"], segment["missingCameras"])

        left_slot, front_slot = segment["slots"]
        self.assertEqual("left_pillar", left_slot["camera"])
        self.assertEqual("front", front_slot["camera"])
        self.assertEqual(1, len(left_slot["fragments"]))
        self.assertEqual(2, len(front_slot["fragments"]))
        self.assertEqual(2.0, front_slot["fragments"][0]["sourceIn"])
        self.assertEqual(10.0, front_slot["fragments"][0]["sourceOut"])
        self.assertEqual(0.0, front_slot["fragments"][1]["sourceIn"])
        self.assertEqual(5.0, front_slot["fragments"][1]["sourceOut"])

    def test_triple_layout_slots_match_stage_spacing(self) -> None:
        player_edits = {
            "trimStartTime": 0.0,
            "trimEndTime": 10.0,
            "exportFormat": "hd",
            "startMarkerView": {"layout": "triple", "cameraKey": "front"},
            "cameraMarkers": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            event_dir.mkdir(parents=True)

            for file_name in (
                "2026-03-28_09-00-00-front.mp4",
                "2026-03-28_09-00-00-left_pillar.mp4",
                "2026-03-28_09-00-00-right_pillar.mp4",
            ):
                (event_dir / file_name).touch()

            with patch(
                "app.renderer.pipeline._probe_video",
                return_value={
                    "duration": 10.0,
                    "frame_rate": 30.0,
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                },
            ):
                render_plan = build_render_plan(
                    event_dir=event_dir,
                    footage_root=footage_root,
                    event_id="SavedClips/2026-03-28_09-12-13",
                    player_edits=player_edits,
                )

        segment = render_plan["segments"][0]
        top_slot, left_slot, right_slot = segment["slots"]
        self.assertEqual((14, 0, 1892, 720), (top_slot["x"], top_slot["y"], top_slot["width"], top_slot["height"]))
        self.assertEqual((320, 720, 640, 360), (left_slot["x"], left_slot["y"], left_slot["width"], left_slot["height"]))
        self.assertEqual((960, 720, 640, 360), (right_slot["x"], right_slot["y"], right_slot["width"], right_slot["height"]))

    def test_build_render_plan_uses_cumulative_playlist_timing(self) -> None:
        player_edits = {
            "trimStartTime": 59.4,
            "trimEndTime": 60.4,
            "exportFormat": "hd",
            "startMarkerView": {"layout": "single", "cameraKey": "front"},
            "cameraMarkers": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            event_dir.mkdir(parents=True)

            for file_name in (
                "2026-03-28_09-00-00-front.mp4",
                "2026-03-28_09-01-00-front.mp4",
            ):
                (event_dir / file_name).touch()

            with patch(
                "app.renderer.pipeline._probe_video",
                return_value={
                    "duration": 59.0,
                    "frame_rate": 30.0,
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                },
            ):
                render_plan = build_render_plan(
                    event_dir=event_dir,
                    footage_root=footage_root,
                    event_id="SavedClips/2026-03-28_09-12-13",
                    player_edits=player_edits,
                )

        slot = render_plan["segments"][0]["slots"][0]
        self.assertEqual(1, len(slot["fragments"]))
        self.assertTrue(slot["fragments"][0]["sourceClip"].endswith("/2026-03-28_09-01-00-front.mp4"))
        self.assertEqual(0.4, slot["fragments"][0]["sourceIn"])
        self.assertEqual(1.4, slot["fragments"][0]["sourceOut"])


if __name__ == "__main__":
    unittest.main()