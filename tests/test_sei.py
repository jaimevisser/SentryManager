from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.sei import (
    build_route_svg_from_gps_points,
    calculate_driver_assist_display,
    ensure_event_processing_marker,
    ensure_sei_sidecars,
    event_needs_route_backfill,
    get_event_route_svg_path,
    get_segment_route_svg_path,
    get_segment_sei_sidecar_path,
)


class SeiTests(unittest.TestCase):
    def test_build_route_svg_from_gps_points_embeds_projection_metadata(self) -> None:
        svg = build_route_svg_from_gps_points(
            [
                (52.0, 5.0),
                (52.0002, 5.0001),
                (52.0004, 5.0003),
            ]
        )

        self.assertIsNotNone(svg)
        self.assertIn("data-route-mean-lat", svg)
        self.assertIn("data-route-mean-lon", svg)
        self.assertIn("data-route-cos-lat", svg)
        self.assertIn("data-route-min-x", svg)
        self.assertIn("data-route-min-y", svg)
        self.assertIn("data-route-span", svg)

    def test_calculate_driver_assist_display_prefers_self_driving(self) -> None:
        display = calculate_driver_assist_display(
            active_duration_ms=900,
            observed_duration_ms=1000,
            self_driving_duration_ms=250,
        )

        self.assertEqual(
            {"label": "FSD", "percent": 25.0, "text": "FSD 25%"},
            display,
        )

    def test_calculate_driver_assist_display_falls_back_to_ap(self) -> None:
        display = calculate_driver_assist_display(
            active_duration_ms=750,
            observed_duration_ms=1000,
            self_driving_duration_ms=0,
        )

        self.assertEqual(
            {"label": "AP", "percent": 75.0, "text": "AP 75%"},
            display,
        )

    def test_calculate_driver_assist_display_returns_none_without_activity(self) -> None:
        self.assertIsNone(
            calculate_driver_assist_display(
                active_duration_ms=0,
                observed_duration_ms=1000,
                self_driving_duration_ms=0,
            )
        )

    def test_event_processing_marker_preserves_unknown_keys_and_writes_ap_display(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            marker_path = event_dir / "sentrymanager.json"
            marker_path.write_text(json.dumps({"custom": "keep", "fsdOnPercent": 88}), encoding="utf-8")

            ensure_event_processing_marker(
                event_dir=event_dir,
                has_autopilot_activity=True,
                has_steering_angle_data=False,
                driver_assist_display={"label": "AP", "percent": 75.0, "text": "AP 75%"},
            )

            payload = json.loads(marker_path.read_text(encoding="utf-8"))

        self.assertEqual("keep", payload["custom"])
        self.assertEqual({"label": "AP", "percent": 75.0, "text": "AP 75%"}, payload["driverAssistDisplay"])
        self.assertNotIn("fsdOnPercent", payload)

    def test_ensure_sei_sidecars_skips_rebuild_when_sidecars_and_marker_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            clip_file = event_dir / "2026-03-31_06-42-49-front.mp4"
            marker_path = event_dir / "sentrymanager.json"

            clip_file.write_bytes(b"clip")
            marker_path.write_text(
                json.dumps(
                    {
                        "hasAutopilotActivity": True,
                        "hasSteeringAngleData": True,
                        "eventCategoryLabel": "Saved",
                        "driverAssistDisplay": {"label": "AP", "percent": 100.0, "text": "AP 100%"},
                    }
                ),
                encoding="utf-8",
            )
            get_event_route_svg_path(event_dir).write_text("<svg></svg>", encoding="utf-8")

            with mock.patch("app.sei.build_sei_sidecar_payload", side_effect=AssertionError("unexpected rebuild")):
                ensure_sei_sidecars([clip_file])

    def test_ensure_sei_sidecars_writes_route_svg_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            clip_file = event_dir / "2026-03-31_06-42-49-front.mp4"
            clip_file.write_bytes(b"clip")

            with mock.patch(
                "app.sei.build_sei_sidecar_payload",
                return_value=(
                    b"sidecar",
                    False,
                    False,
                    0,
                    0,
                    0,
                    "<svg viewBox='0 0 10 10'></svg>",
                    [(52.0, 5.0), (52.0001, 5.0001)],
                ),
            ):
                ensure_sei_sidecars([clip_file])

            sidecar_path = get_segment_sei_sidecar_path(event_dir, "2026-03-31_06-42-49")
            route_svg_path = get_segment_route_svg_path(event_dir, "2026-03-31_06-42-49")
            combined_route_svg_path = get_event_route_svg_path(event_dir)

            self.assertTrue(sidecar_path.is_file())
            self.assertTrue(route_svg_path.is_file())
            self.assertTrue(combined_route_svg_path.is_file())
            self.assertEqual("<svg viewBox='0 0 10 10'></svg>", route_svg_path.read_text(encoding="utf-8"))

    def test_ensure_sei_sidecars_removes_stale_sidecar_and_route_when_no_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            clip_file = event_dir / "2026-03-31_06-42-49-front.mp4"
            clip_file.write_bytes(b"clip")

            sidecar_path = get_segment_sei_sidecar_path(event_dir, "2026-03-31_06-42-49")
            route_svg_path = get_segment_route_svg_path(event_dir, "2026-03-31_06-42-49")
            sidecar_path.write_bytes(b"old")
            route_svg_path.write_text("<svg></svg>", encoding="utf-8")

            with mock.patch(
                "app.sei.build_sei_sidecar_payload",
                return_value=(None, False, False, 0, 0, 0, None, []),
            ):
                ensure_sei_sidecars([clip_file])

            self.assertFalse(sidecar_path.exists())
            self.assertFalse(route_svg_path.exists())

    def test_event_needs_route_backfill_when_sidecar_exists_without_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            sidecar_path = get_segment_sei_sidecar_path(event_dir, "2026-03-31_06-42-49")
            sidecar_path.write_bytes(b"sidecar")

            self.assertTrue(event_needs_route_backfill(event_dir))

    def test_event_needs_route_backfill_false_when_route_exists_for_all_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            sidecar_path = get_segment_sei_sidecar_path(event_dir, "2026-03-31_06-42-49")
            route_svg_path = get_segment_route_svg_path(event_dir, "2026-03-31_06-42-49")
            combined_route_svg_path = get_event_route_svg_path(event_dir)
            sidecar_path.write_bytes(b"sidecar")
            route_svg_path.write_text("<svg></svg>", encoding="utf-8")
            combined_route_svg_path.write_text(
                (
                    '<svg data-route-projection-version="2" '
                    'data-route-mean-lat="52" data-route-mean-lon="5" '
                    'data-route-cos-lat="0.61" data-route-min-x="0" '
                    'data-route-min-y="0" data-route-span="1"></svg>'
                ),
                encoding="utf-8",
            )

            self.assertFalse(event_needs_route_backfill(event_dir))

    def test_event_needs_route_backfill_when_combined_route_lacks_projection_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir)
            sidecar_path = get_segment_sei_sidecar_path(event_dir, "2026-03-31_06-42-49")
            route_svg_path = get_segment_route_svg_path(event_dir, "2026-03-31_06-42-49")
            combined_route_svg_path = get_event_route_svg_path(event_dir)
            sidecar_path.write_bytes(b"sidecar")
            route_svg_path.write_text("<svg></svg>", encoding="utf-8")
            combined_route_svg_path.write_text("<svg viewBox='0 0 1000 1000'></svg>", encoding="utf-8")

            self.assertTrue(event_needs_route_backfill(event_dir))


if __name__ == "__main__":
    unittest.main()
