from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.sei import calculate_driver_assist_display, ensure_event_processing_marker


class SeiTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()