from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.renderer.pipeline import (
    _load_route_map_overlay,
    _draw_heading_cell,
    _draw_top_right_route_overlay,
    _draw_telemetry_frame,
    _project_route_dot_to_overlay,
    _get_layout_slot_specs,
    build_render_plan,
    get_normalized_edit_segments,
    render_event,
)


class RendererPipelineTests(unittest.TestCase):
    def test_render_event_prunes_older_successful_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            output_dir = event_dir / "exports"
            current_intermediate_dir = output_dir / "20260503T120314Z-hd-segments"
            old_intermediate_dir = output_dir / "20260501T101010Z-hd-segments"
            output_dir.mkdir(parents=True)
            old_intermediate_dir.mkdir()
            (old_intermediate_dir / "seg-001.mp4").write_text("old", encoding="utf-8")
            old_output_path = output_dir / "2026-03-28_09-12-13-hd-20260501T101010Z.mp4"
            old_plan_path = output_dir / "2026-03-28_09-12-13-hd-20260501T101010Z.render-plan.json"
            old_output_path.write_text("old video", encoding="utf-8")
            old_plan_path.write_text("{}", encoding="utf-8")
            keep_path = output_dir / "keep.txt"
            keep_path.write_text("keep", encoding="utf-8")

            render_plan = {
                "outputProfile": "hd",
                "outputPath": str(output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.mp4"),
                "intermediateDir": str(current_intermediate_dir),
                "renderPlanPath": str(output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.render-plan.json"),
                "segments": [
                    {
                        "segmentId": "seg-001",
                        "missingCameras": ["left_pillar"],
                    }
                ],
                "frameSize": {"width": 1920, "height": 1080},
                "frameRate": 30.0,
                "mediaIndex": [],
            }

            def fake_render_segments(**_: object) -> list[Path]:
                current_intermediate_dir.mkdir(parents=True, exist_ok=True)
                segment_output = current_intermediate_dir / "seg-001.mp4"
                segment_output.write_text("segment", encoding="utf-8")
                return [segment_output]

            def fake_run_ffmpeg(command: list[str]) -> None:
                Path(command[-1]).write_text("new video", encoding="utf-8")

            with patch("app.renderer.pipeline.build_render_plan", return_value=render_plan):
                with patch("app.renderer.pipeline._load_event_processing_state", return_value={}):
                    with patch("app.renderer.pipeline._get_event_driver_assist_display", return_value=None):
                        with patch("app.renderer.pipeline._render_plan_segments", side_effect=fake_render_segments):
                            with patch("app.renderer.pipeline._run_ffmpeg", side_effect=fake_run_ffmpeg):
                                result = render_event(
                                    event_dir=event_dir,
                                    footage_root=footage_root,
                                    event_id="SavedClips/2026-03-28_09-12-13",
                                    player_edits={},
                                    output_profile="hd",
                                )

            self.assertEqual(str(output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.mp4"), result["outputPath"])
            self.assertTrue((output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.mp4").is_file())
            self.assertTrue((output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.render-plan.json").is_file())
            self.assertFalse(old_output_path.exists())
            self.assertFalse(old_plan_path.exists())
            self.assertFalse(old_intermediate_dir.exists())
            self.assertFalse(current_intermediate_dir.exists())
            self.assertTrue(keep_path.is_file())

    def test_render_event_aggregates_combined_driver_assist_display(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            child_dir = footage_root / "SavedClips" / "2026-03-28_09-13-13"
            output_dir = owner_dir / "exports"
            intermediate_dir = output_dir / "20260503T120314Z-hd-segments"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (child_dir / "2026-03-28_09-13-13-front.mp4").write_text("", encoding="utf-8")
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps(
                    {
                        "combinedEvent": {"memberClipNames": [child_dir.name]},
                        "autopilotObservedDurationMs": 1000,
                        "autopilotActiveDurationMs": 1000,
                        "selfDrivingDurationMs": 1000,
                    }
                ),
                encoding="utf-8",
            )
            (child_dir / "sentrymanager.json").write_text(
                json.dumps(
                    {
                        "autopilotObservedDurationMs": 4000,
                        "autopilotActiveDurationMs": 1000,
                        "selfDrivingDurationMs": 1000,
                    }
                ),
                encoding="utf-8",
            )

            render_plan = {
                "outputProfile": "hd",
                "outputPath": str(output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.mp4"),
                "intermediateDir": str(intermediate_dir),
                "renderPlanPath": str(output_dir / "2026-03-28_09-12-13-hd-20260503T120314Z.render-plan.json"),
                "segments": [
                    {
                        "segmentId": "seg-001",
                        "missingCameras": [],
                    }
                ],
                "frameSize": {"width": 1920, "height": 1080},
                "frameRate": 30.0,
                "mediaIndex": [],
            }

            def fake_render_segments(**kwargs: object) -> list[Path]:
                self.assertEqual(
                    {"label": "FSD", "percent": 25.0, "text": "FSD 25%"},
                    kwargs["event_driver_assist_display"],
                )
                intermediate_dir.mkdir(parents=True, exist_ok=True)
                segment_output = intermediate_dir / "seg-001.mp4"
                segment_output.write_text("segment", encoding="utf-8")
                return [segment_output]

            def fake_run_ffmpeg(command: list[str]) -> None:
                Path(command[-1]).write_text("new video", encoding="utf-8")

            with patch("app.renderer.pipeline.build_render_plan", return_value=render_plan):
                with patch("app.renderer.pipeline._load_event_payload", return_value={}):
                    with patch("app.renderer.pipeline._render_plan_segments", side_effect=fake_render_segments):
                        with patch("app.renderer.pipeline._run_ffmpeg", side_effect=fake_run_ffmpeg):
                            render_event(
                                event_dir=owner_dir,
                                footage_root=footage_root,
                                event_id="SavedClips/2026-03-28_09-12-13",
                                player_edits={},
                                output_profile="hd",
                            )

    def test_draw_telemetry_frame_renders_location_in_top_left_safe_zone(self) -> None:
        frame, has_overlay = _draw_telemetry_frame(
            frame_size={"width": 1280, "height": 720},
            safe_zones={
                "left": None,
                "right": None,
                "topLeft": (0.0, 0.0, 220.0, 160.0),
            },
            segment_time=0.0,
            telemetry_point=None,
            event_driver_assist_display=None,
            event_base_timestamp=None,
            event_location_label="Parallelweg, Oss",
        )

        self.assertTrue(has_overlay)
        self.assertIsNotNone(frame.getbbox())

    def test_load_route_map_overlay_uses_trimmed_selected_only_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)

            with patch(
                "app.renderer.pipeline.build_event_route_svg_from_event_dirs",
                return_value=(
                    '<svg data-route-projection-version="2" '
                    'data-route-mean-lat="52" data-route-mean-lon="5" '
                    'data-route-cos-lat="0.61" data-route-min-x="0" '
                    'data-route-min-y="0" data-route-span="1">'
                    '<path d="M 0 0 L 10 10" fill="none" stroke="#eef8ff" stroke-width="24"/>'
                    '</svg>'
                ),
            ) as route_svg_mock:
                with patch(
                    "app.renderer.pipeline._render_svg_payload_to_rgba_image",
                    return_value=Image.new("RGBA", (120, 120), (238, 248, 255, 255)),
                ) as render_svg_mock:
                    overlay = _load_route_map_overlay(
                        event_dir,
                        (0.0, 0.0, 120.0, 120.0),
                        trim_start_time=1.5,
                        trim_end_time=4.5,
                    )

        self.assertIsNotNone(overlay)
        route_svg_mock.assert_called_once_with(
            [event_dir],
            trim_start_time=1.5,
            trim_end_time=4.5,
            mode="selected-only",
        )
        render_svg_mock.assert_called_once()

    def test_draw_telemetry_frame_renders_route_map_in_top_right_safe_zone(self) -> None:
        route_map = Image.new("RGBA", (120, 120), (238, 248, 255, 230))
        frame, has_overlay = _draw_telemetry_frame(
            frame_size={"width": 1280, "height": 720},
            safe_zones={
                "left": None,
                "right": None,
                "topLeft": None,
                "topRight": (1060.0, 0.0, 1180.0, 120.0),
            },
            segment_time=0.0,
            telemetry_point=None,
            route_map_overlay={
                "image": route_map,
                "projection": {
                    "mean_lat": 0.0,
                    "mean_lon": 0.0,
                    "cos_lat": 1.0,
                    "min_x": 0.0,
                    "min_y": 0.0,
                    "span": 1.0,
                },
            },
            event_driver_assist_display=None,
            event_base_timestamp=None,
            event_location_label=None,
        )

        self.assertTrue(has_overlay)
        overlay_pixel = frame.getpixel((1100, 60))
        self.assertGreater(overlay_pixel[3], 0)

    def test_draw_telemetry_frame_projects_route_dot_from_sample(self) -> None:
        route_map_overlay = {
            "image": Image.new("RGBA", (200, 200), (238, 248, 255, 255)),
            "projection": {
                "mean_lat": 0.0,
                "mean_lon": 0.0,
                "cos_lat": 1.0,
                "min_x": 0.0,
                "min_y": 0.0,
                "span": 1.0,
            },
        }
        rect = (1000.0, 0.0, 1200.0, 200.0)

        image_without_dot = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        draw_without_dot = ImageDraw.Draw(image_without_dot)
        rendered_without_dot = _draw_top_right_route_overlay(
            image_without_dot,
            draw_without_dot,
            rect,
            route_map_overlay,
            sample=None,
        )
        baseline_pixel = image_without_dot.getpixel((1100, 100))

        image_with_dot = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        draw_with_dot = ImageDraw.Draw(image_with_dot)
        rendered_with_dot = _draw_top_right_route_overlay(
            image_with_dot,
            draw_with_dot,
            rect,
            route_map_overlay,
            sample={
                "presenceBits": (1 << 10) | (1 << 11),
                "latitudeE7": 5_000_000,
                "longitudeE7": 5_000_000,
            },
        )
        dot_pixel = image_with_dot.getpixel((1100, 100))

        self.assertTrue(rendered_without_dot)
        self.assertTrue(rendered_with_dot)
        self.assertNotEqual(baseline_pixel, dot_pixel)

    def test_project_route_dot_to_overlay_accounts_for_letterboxing(self) -> None:
        projected = _project_route_dot_to_overlay(
            sample={
                "presenceBits": (1 << 10) | (1 << 11),
                "latitudeE7": 0,
                "longitudeE7": 0,
            },
            projection={
                "mean_lat": 0.0,
                "mean_lon": 0.0,
                "cos_lat": 1.0,
                "min_x": 0.0,
                "min_y": 0.0,
                "span": 1.0,
            },
            width=200,
            height=120,
        )

        self.assertIsNotNone(projected)
        assert projected is not None
        self.assertAlmostEqual(44.8, projected[0], places=1)
        self.assertAlmostEqual(115.2, projected[1], places=1)

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

    def test_double_layout_slots_use_even_widths(self) -> None:
        left_slot, right_slot = _get_layout_slot_specs("double", "front", 1920, 1080)

        self.assertEqual((14, 0, 940, 1080), (left_slot["x"], left_slot["y"], left_slot["width"], left_slot["height"]))
        self.assertEqual((964, 0, 942, 1080), (right_slot["x"], right_slot["y"], right_slot["width"], right_slot["height"]))

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

    def test_build_render_plan_includes_combined_member_event_clips(self) -> None:
        player_edits = {
            "trimStartTime": 59.4,
            "trimEndTime": 60.4,
            "exportFormat": "hd",
            "startMarkerView": {"layout": "single", "cameraKey": "front"},
            "cameraMarkers": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-28_09-12-13"
            child_dir = footage_root / "SavedClips" / "2026-03-28_09-13-13"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-28_09-12-13-front.mp4").touch()
            (child_dir / "2026-03-28_09-13-13-front.mp4").touch()
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedEvent": {"memberClipNames": [child_dir.name]}}),
                encoding="utf-8",
            )

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
                    event_dir=owner_dir,
                    footage_root=footage_root,
                    event_id="SavedClips/2026-03-28_09-12-13",
                    player_edits=player_edits,
                )

        slot = render_plan["segments"][0]["slots"][0]
        self.assertEqual(1, len(slot["fragments"]))
        self.assertTrue(slot["fragments"][0]["sourceClip"].endswith("/2026-03-28_09-13-13-front.mp4"))
        self.assertEqual(0.4, slot["fragments"][0]["sourceIn"])
        self.assertEqual(1.4, slot["fragments"][0]["sourceOut"])

    def test_load_svg_icon_scales_up_to_requested_target_size(self) -> None:
        png_buffer = io.BytesIO()
        Image.new("RGBA", (24, 24), (255, 255, 255, 255)).save(png_buffer, format="PNG")

        with patch.dict("app.renderer.pipeline.SVG_ICON_CACHE", {}, clear=True):
            with patch(
                "app.renderer.pipeline.subprocess.run",
                return_value=unittest.mock.Mock(returncode=0, stdout=png_buffer.getvalue()),
            ):
                from app.renderer.pipeline import _load_svg_icon

                icon = _load_svg_icon("navigation.svg", 40)

        self.assertIsNotNone(icon)
        self.assertEqual((40, 40), icon.size)

    def test_draw_heading_cell_uses_full_safe_zone_scale(self) -> None:
        image = Image.new("RGBA", (126, 235), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        rendered = _draw_heading_cell(
            image,
            draw,
            (10, 60, 116, 110),
            (0, 0, 126, 235),
            {"headingLabel": "W", "headingDegrees": 270},
        )

        self.assertTrue(rendered)
        alpha_bounds = image.getchannel("A").getbbox()
        self.assertIsNotNone(alpha_bounds)
        self.assertGreaterEqual(alpha_bounds[2] - alpha_bounds[0], 24)
        self.assertGreaterEqual(alpha_bounds[3] - alpha_bounds[1], 24)


if __name__ == "__main__":
    unittest.main()