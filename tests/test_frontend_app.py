from __future__ import annotations

import importlib
import json
import os
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

    def test_player_edits_route_persists_multiline_notes_to_notes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            (event_dir / "2026-03-31_06-42-49-front.mp4").write_bytes(b"")
            (event_dir / "sentrymanager.json").write_text("{}", encoding="utf-8")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                response = app.test_client().post(
                    "/events/SavedClips/2026-03-31_06-53-21/player-edits",
                    json={
                        "trimStartTime": 0,
                        "trimEndTime": 1,
                        "exportFormat": "hd",
                        "startMarkerView": {"layout": "single", "cameraKey": "front"},
                        "cameraMarkers": [],
                        "notes": "First line\nSecond line",
                    },
                )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

            saved_state = json.loads((event_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            saved_notes = (event_dir / "notes.txt").read_text(encoding="utf-8")

        self.assertEqual(200, response.status_code)
        self.assertEqual("First line\nSecond line", saved_notes)
        self.assertNotIn("notes", saved_state.get("playerEdits", {}))

    def test_combined_route_svg_endpoint_renders_trimmed_highlight_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            (event_dir / "route-combined.svg").write_text("<svg></svg>", encoding="utf-8")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(
                    frontend_app_module,
                    "build_event_route_svg_content",
                    return_value='<svg><path stroke="#6f7782"/><path stroke="#eef8ff"/></svg>',
                ) as route_svg_mock:
                    response = app.test_client().get(
                        "/event-route-svg-combined/SavedClips/2026-03-31_06-53-21?trimStartTime=1.5&trimEndTime=4.5&mode=highlight"
                    )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        self.assertEqual("image/svg+xml; charset=utf-8", response.content_type)
        self.assertIn('stroke="#6f7782"', response.get_data(as_text=True))
        route_svg_mock.assert_called_once_with(
            event_dir,
            trim_start_time=1.5,
            trim_end_time=4.5,
            mode="highlight",
        )

    def test_player_edits_route_uses_combined_owner_folder_for_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (owner_dir / "sentrymanager.json").write_text("{}", encoding="utf-8")
            (child_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedIntoClipName": owner_dir.name}),
                encoding="utf-8",
            )

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                response = app.test_client().post(
                    "/events/SavedClips/2026-03-31_06-54-21/player-edits",
                    json={
                        "trimStartTime": 0,
                        "trimEndTime": 1,
                        "exportFormat": "hd",
                        "startMarkerView": {"layout": "single", "cameraKey": "front"},
                        "cameraMarkers": [],
                        "notes": "Combined clip note",
                    },
                )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

            saved_owner_notes = (owner_dir / "notes.txt").read_text(encoding="utf-8")
            child_notes_exists = (child_dir / "notes.txt").exists()

        self.assertEqual(200, response.status_code)
        self.assertEqual("Combined clip note", saved_owner_notes)
        self.assertFalse(child_notes_exists)

    def test_load_event_trigger_camera_key_uses_swapped_sentry_side_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir) / "SentryClips" / "2026-03-27_10-42-07"
            event_dir.mkdir(parents=True)

            expected_camera_keys = {
                3: "left_pillar",
                4: "right_pillar",
                5: "left_repeater",
                6: "right_repeater",
            }

            for camera_number, expected_camera_key in expected_camera_keys.items():
                (event_dir / "event.json").write_text(
                    f'{{"camera": {camera_number}}}',
                    encoding="utf-8",
                )
                self.assertEqual(expected_camera_key, frontend_app_module.load_event_trigger_camera_key(event_dir))

    def test_get_initial_player_start_time_uses_sentry_preroll_env_var(self) -> None:
        event = frontend_app_module.EventSummary(
            name="2026-03-27_10-42-07",
            path="SentryClips/2026-03-27_10-42-07",
            category="SentryClips",
            category_label="Sentry",
            clip_count=1,
            cameras=["Front"],
            timestamp=None,
            start_timestamp=None,
            day_label="Unknown day",
            time_label="Unknown time",
            thumbnail_path=None,
            location_label=None,
            trigger_offset_seconds=100.0,
            end_timestamp=None,
        )

        with mock.patch.dict(os.environ, {"SENTRY_PLAYER_PREROLL_SECONDS": "20"}, clear=False):
            self.assertEqual(80.0, frontend_app_module.get_initial_player_start_time(event))

        with mock.patch.dict(os.environ, {"SENTRY_PLAYER_PREROLL_SECONDS": "5"}, clear=False):
            self.assertEqual(95.0, frontend_app_module.get_initial_player_start_time(event))

    def test_get_initial_player_start_time_falls_back_to_default_for_invalid_sentry_preroll(self) -> None:
        event = frontend_app_module.EventSummary(
            name="2026-03-27_10-42-07",
            path="SentryClips/2026-03-27_10-42-07",
            category="SentryClips",
            category_label="Sentry",
            clip_count=1,
            cameras=["Front"],
            timestamp=None,
            start_timestamp=None,
            day_label="Unknown day",
            time_label="Unknown time",
            thumbnail_path=None,
            location_label=None,
            trigger_offset_seconds=100.0,
            end_timestamp=None,
        )

        with mock.patch.dict(os.environ, {"SENTRY_PLAYER_PREROLL_SECONDS": "not-a-number"}, clear=False):
            self.assertEqual(80.0, frontend_app_module.get_initial_player_start_time(event))

    def test_discover_event_directories_hides_combined_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (child_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedIntoClipName": owner_dir.name}),
                encoding="utf-8",
            )

            event_directories = frontend_app_module.discover_event_directories(footage_root)

        self.assertEqual([owner_dir], event_directories)

    def test_build_camera_playlists_payload_includes_combined_member_clips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedEvent": {"memberClipNames": [child_dir.name]}}),
                encoding="utf-8",
            )

            playlists = frontend_app_module.build_camera_playlists_payload(owner_dir, footage_root)

        self.assertEqual(2, len(playlists["front"]))
        self.assertEqual("SavedClips/2026-03-31_06-53-21", playlists["front"][0].source_event_path)
        self.assertEqual("SavedClips/2026-03-31_06-54-21", playlists["front"][1].source_event_path)

    def test_build_playlist_payload_includes_server_side_clip_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            clip_path = event_dir / "2026-03-31_06-53-21-front.mp4"
            clip_path.write_bytes(b"")

            camera_playlists = {
                "front": [
                    frontend_app_module.EventClip(
                        camera_key="front",
                        camera_label="Front",
                        segment_key="2026-03-31_06-53-21",
                        segment_label="06:53:21",
                        file_name=clip_path.name,
                        file_path=str(clip_path.relative_to(footage_root)),
                        source_event_path="SavedClips/2026-03-31_06-53-21",
                    )
                ]
            }

            app = frontend_app_module.app
            with app.test_request_context():
                with mock.patch.object(frontend_app_module, "get_clip_duration_seconds", return_value=711.25):
                    payload = frontend_app_module.build_playlist_payload(
                        event_dir,
                        "SavedClips/2026-03-31_06-53-21",
                        footage_root,
                        camera_playlists,
                    )

        self.assertEqual(711.25, payload["front"][0]["duration"])

    def test_infer_exact_event_time_window_probes_only_last_segment_and_caches_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_dir = Path(temp_dir) / "SavedClips" / "2026-07-21_15-44-02"
            event_dir.mkdir(parents=True)
            clip_files = [
                event_dir / "2026-07-21_15-43-33-front.mp4",
                event_dir / "2026-07-21_15-43-59-front.mp4",
                event_dir / "2026-07-21_15-44-45-front.mp4",
            ]
            for clip_file in clip_files:
                clip_file.write_bytes(b"")

            with mock.patch.object(frontend_app_module, "get_clip_duration_seconds", return_value=30.8283) as duration_mock:
                time_window = frontend_app_module.infer_exact_event_time_window(event_dir, clip_files=clip_files)

            self.assertIsNotNone(time_window)
            self.assertEqual(frontend_app_module.infer_event_timestamp("2026-07-21_15-43-33"), time_window[0])
            self.assertEqual(frontend_app_module.infer_event_timestamp("2026-07-21_15-44-45") + frontend_app_module.timedelta(seconds=30.8283), time_window[1])
            duration_mock.assert_called_once_with(clip_files[-1])
            self.assertTrue((event_dir / "event-window.json").is_file())

            with mock.patch.object(
                frontend_app_module,
                "get_clip_duration_seconds",
                side_effect=AssertionError("duration probe should not run when cache is valid"),
            ):
                cached_time_window = frontend_app_module.infer_exact_event_time_window(event_dir, clip_files=clip_files)

            self.assertEqual(time_window, cached_time_window)

    def test_infer_event_time_window_defaults_to_segment_window_without_duration_probes(self) -> None:
        clip_files = [
            Path("2026-07-21_15-43-33-front.mp4"),
            Path("2026-07-21_15-43-59-front.mp4"),
            Path("2026-07-21_15-44-45-front.mp4"),
        ]

        with mock.patch.object(
            frontend_app_module,
            "get_clip_duration_seconds",
            side_effect=AssertionError("duration probe should not run"),
        ):
            time_window = frontend_app_module.infer_event_time_window_from_clip_files(clip_files)

        self.assertIsNotNone(time_window)
        self.assertEqual(frontend_app_module.infer_event_timestamp("2026-07-21_15-43-33"), time_window[0])
        self.assertEqual(
            frontend_app_module.infer_event_timestamp("2026-07-21_15-44-45")
            + frontend_app_module.timedelta(seconds=frontend_app_module.COMBINE_SEGMENT_SECONDS),
            time_window[1],
        )

    def test_get_combinable_event_directories_uses_actual_clip_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_directories = [
                footage_root / "SavedClips" / "2026-07-21_15-44-02",
                footage_root / "SavedClips" / "2026-07-21_15-44-51",
                footage_root / "SavedClips" / "2026-07-21_15-45-20",
            ]
            clip_names = [
                "2026-07-21_15-43-33-front.mp4",
                "2026-07-21_15-43-59-front.mp4",
                "2026-07-21_15-44-45-front.mp4",
            ]
            duration_map = {
                "2026-07-21_15-43-33-front.mp4": 25.7406,
                "2026-07-21_15-43-59-front.mp4": 46.1071,
                "2026-07-21_15-44-45-front.mp4": 30.8283,
            }

            for event_dir, clip_name in zip(event_directories, clip_names):
                event_dir.mkdir(parents=True)
                (event_dir / clip_name).write_bytes(b"")

            with mock.patch.object(
                frontend_app_module,
                "get_clip_duration_seconds",
                side_effect=lambda clip_file: duration_map[clip_file.name],
            ):
                owner_dir, ordered_directories = frontend_app_module.get_combinable_event_directories(
                    footage_root,
                    event_directories,
                )

        self.assertEqual(event_directories[0], owner_dir)
        self.assertEqual(event_directories, ordered_directories)

    def test_combine_selection_status_reports_allowed_for_exact_consecutive_saved_clips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_directories = [
                footage_root / "SavedClips" / "2026-07-21_15-44-02",
                footage_root / "SavedClips" / "2026-07-21_15-44-51",
            ]
            clip_names = [
                "2026-07-21_15-43-33-front.mp4",
                "2026-07-21_15-43-59-front.mp4",
            ]
            duration_map = {
                "2026-07-21_15-43-33-front.mp4": 25.7406,
                "2026-07-21_15-43-59-front.mp4": 46.1071,
            }

            for event_dir, clip_name in zip(event_directories, clip_names):
                event_dir.mkdir(parents=True)
                (event_dir / clip_name).write_bytes(b"")

            with mock.patch.object(
                frontend_app_module,
                "get_clip_duration_seconds",
                side_effect=lambda clip_file: duration_map[clip_file.name],
            ):
                status = frontend_app_module.get_combine_selection_status(footage_root, event_directories)

        self.assertEqual(
            {
                "allowed": True,
                "error": None,
                "ownerEventPath": "SavedClips/2026-07-21_15-44-02",
                "orderedEventPaths": [
                    "SavedClips/2026-07-21_15-44-02",
                    "SavedClips/2026-07-21_15-44-51",
                ],
            },
            status,
        )

    def test_combine_eligibility_route_reports_disallowed_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SentryClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SentryClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                response = app.test_client().post(
                    "/events/combine/eligibility",
                    json={
                        "eventPaths": [
                            "SentryClips/2026-03-31_06-53-21",
                            "SentryClips/2026-03-31_06-54-21",
                        ],
                    },
                )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "allowed": False,
                "error": "Only Saved clips can be combined.",
            },
            response.get_json(),
        )

    def test_index_page_does_not_render_exact_window_dataset_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            event_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            event_dir.mkdir(parents=True)
            (event_dir / "2026-03-31_06-42-49-front.mp4").write_bytes(b"")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                response = app.test_client().get("/")
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("data-event-timestamp=", html)
        self.assertNotIn("data-event-start-timestamp=", html)
        self.assertNotIn("data-event-end-timestamp=", html)

    def test_combine_events_route_persists_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "rebuild_event_route_svg_from_event_dirs", return_value=True) as rebuild_mock:
                    response = app.test_client().post(
                        "/events/combine",
                        json={
                            "eventPaths": [
                                "SavedClips/2026-03-31_06-54-21",
                                "SavedClips/2026-03-31_06-53-21",
                            ],
                        },
                    )
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

            owner_state = json.loads((owner_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            child_state = json.loads((child_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            visible_directories = frontend_app_module.discover_event_directories(footage_root)

        self.assertEqual(200, response.status_code)
        self.assertEqual(["2026-03-31_06-54-21"], owner_state["combinedEvent"]["memberClipNames"])
        self.assertEqual(1, owner_state["combinedEvent"]["routeSvgVersion"])
        self.assertEqual("2026-03-31_06-53-21", child_state["combinedIntoClipName"])
        self.assertEqual([owner_dir], visible_directories)
        rebuild_mock.assert_called_once_with(owner_dir, [owner_dir, child_dir])

    def test_combined_owner_event_page_includes_combined_route_svg_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (owner_dir / "route-combined.svg").write_text("<svg></svg>", encoding="utf-8")
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedEvent": {"memberClipNames": [child_dir.name]}}),
                encoding="utf-8",
            )
            (child_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedIntoClipName": owner_dir.name}),
                encoding="utf-8",
            )

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "queue_event_processing"):
                    with mock.patch.object(frontend_app_module, "rebuild_event_route_svg_from_event_dirs", return_value=True) as rebuild_mock:
                        response = app.test_client().get("/events/SavedClips/2026-03-31_06-53-21")
                owner_state = json.loads((owner_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        self.assertIn(
            "/event-route-svg-combined/SavedClips/2026-03-31_06-53-21",
            response.get_data(as_text=True),
        )
        self.assertEqual(1, owner_state["combinedEvent"]["routeSvgVersion"])
        rebuild_mock.assert_called_once_with(owner_dir, [owner_dir, child_dir])

    def test_combined_owner_event_page_aggregates_driver_assist_display(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
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
                        "combinedIntoClipName": owner_dir.name,
                        "autopilotObservedDurationMs": 1000,
                        "autopilotActiveDurationMs": 0,
                        "selfDrivingDurationMs": 0,
                    }
                ),
                encoding="utf-8",
            )

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "queue_event_processing"):
                    response = app.test_client().get("/events/SavedClips/2026-03-31_06-53-21")
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

        self.assertEqual(200, response.status_code)
        self.assertIn("FSD 50%", response.get_data(as_text=True))

    def test_uncombine_event_directory_clears_combined_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedEvent": {"memberClipNames": [child_dir.name]}}),
                encoding="utf-8",
            )
            (child_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedIntoClipName": owner_dir.name}),
                encoding="utf-8",
            )

            with mock.patch.object(frontend_app_module, "rebuild_event_route_svg_from_event_dirs", return_value=True) as rebuild_mock:
                result = frontend_app_module.uncombine_event_directory(owner_dir)

            owner_state = json.loads((owner_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            child_state = json.loads((child_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            visible_directories = frontend_app_module.discover_event_directories(footage_root)

        self.assertTrue(result)
        self.assertNotIn("combinedEvent", owner_state)
        self.assertNotIn("combinedIntoClipName", child_state)
        self.assertEqual([owner_dir, child_dir], visible_directories)
        rebuild_mock.assert_called_once_with(owner_dir, [owner_dir])

    def test_uncombine_event_route_clears_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            footage_root = Path(temp_dir) / "TeslaCam"
            owner_dir = footage_root / "SavedClips" / "2026-03-31_06-53-21"
            child_dir = footage_root / "SavedClips" / "2026-03-31_06-54-21"
            owner_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)
            (owner_dir / "2026-03-31_06-53-21-front.mp4").write_bytes(b"")
            (child_dir / "2026-03-31_06-54-21-front.mp4").write_bytes(b"")
            (owner_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedEvent": {"memberClipNames": [child_dir.name]}}),
                encoding="utf-8",
            )
            (child_dir / "sentrymanager.json").write_text(
                json.dumps({"combinedIntoClipName": owner_dir.name}),
                encoding="utf-8",
            )

            app = frontend_app_module.app
            previous_root = app.config["TESLACAM_ROOT"]
            app.config["TESLACAM_ROOT"] = str(footage_root)
            try:
                with mock.patch.object(frontend_app_module, "rebuild_event_route_svg_from_event_dirs", return_value=True) as rebuild_mock:
                    response = app.test_client().post("/events/SavedClips/2026-03-31_06-53-21/uncombine")
            finally:
                app.config["TESLACAM_ROOT"] = previous_root

            owner_state = json.loads((owner_dir / "sentrymanager.json").read_text(encoding="utf-8"))
            child_state = json.loads((child_dir / "sentrymanager.json").read_text(encoding="utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertNotIn("combinedEvent", owner_state)
        self.assertNotIn("combinedIntoClipName", child_state)
        rebuild_mock.assert_called_once_with(owner_dir, [owner_dir])


if __name__ == "__main__":
    unittest.main()