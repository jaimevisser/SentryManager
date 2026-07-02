from __future__ import annotations

from pathlib import Path
from types import ModuleType
import shutil

from flask import Flask, abort, jsonify, render_template, request, send_file


def register_routes(app: Flask, frontend_module: ModuleType) -> None:
    @app.route("/event-thumbnails/<path:event_path>")
    def event_thumbnail(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        thumbnail_path = frontend_module.require_file_path(footage_root, str(Path(event_path) / "thumb.png"))
        return send_file(thumbnail_path, conditional=True, max_age=3600)

    @app.route("/event-clips/<path:clip_path>")
    def event_clip(clip_path: str):
        footage_root = frontend_module.get_footage_root(app)
        clip_file = frontend_module.require_file_path(footage_root, clip_path)
        return send_file(clip_file, conditional=True)

    @app.route("/event-telemetry/<path:event_path>/<segment_key>")
    def event_telemetry(event_path: str, segment_key: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.require_event_dir(footage_root, event_path)

        sidecar_file = frontend_module.get_segment_sei_sidecar_path(event_dir, segment_key)
        if not sidecar_file.is_file() or not frontend_module._is_within_root(sidecar_file, footage_root):
            abort(404)

        return send_file(sidecar_file, mimetype="application/octet-stream", conditional=True)

    @app.route("/event-route-svg/<path:event_path>/<segment_key>")
    def event_route_svg(event_path: str, segment_key: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.require_event_dir(footage_root, event_path)

        route_svg_file = frontend_module.get_segment_route_svg_path(event_dir, segment_key)
        if not route_svg_file.is_file() or not frontend_module._is_within_root(route_svg_file, footage_root):
            abort(404)

        return send_file(route_svg_file, mimetype="image/svg+xml", conditional=True)

    @app.route("/event-route-svg-combined/<path:event_path>")
    def event_route_svg_combined(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.require_event_dir(footage_root, event_path)

        route_svg_file = frontend_module.get_event_route_svg_path(event_dir)
        if not route_svg_file.is_file() or not frontend_module._is_within_root(route_svg_file, footage_root):
            abort(404)

        return send_file(route_svg_file, mimetype="image/svg+xml", conditional=True)

    @app.route("/events/<path:event_path>")
    def event_player(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.require_event_dir(footage_root, event_path)
        frontend_module.queue_event_processing(event_dir)
        template_context = frontend_module.build_event_player_template_context(event_dir, footage_root)
        if template_context is None:
            abort(404)
        return render_template("event_player.html", **template_context)

    @app.route("/")
    def index() -> str:
        footage_root = Path(app.config["TESLACAM_ROOT"])
        event_directories = frontend_module.discover_event_directories(footage_root)
        frontend_module.queue_discovered_event_processing(event_directories)
        event_summaries = frontend_module.discover_event_summaries(footage_root, event_directories=event_directories)
        day_groups = frontend_module.group_events_by_day(event_summaries)
        return render_template("index.html", day_groups=day_groups)

    @app.post("/events/delete")
    def delete_events():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid delete request."}), 400

        raw_event_paths = payload.get("eventPaths")
        if not isinstance(raw_event_paths, list) or len(raw_event_paths) == 0:
            return jsonify({"error": "Select at least one clip to delete."}), 400

        footage_root = frontend_module.get_footage_root(app)
        event_directories: list[Path] = []
        deleted_paths: list[str] = []
        seen_directories: set[Path] = set()

        for raw_event_path in raw_event_paths:
            if not isinstance(raw_event_path, str) or not raw_event_path.strip():
                return jsonify({"error": "Invalid clip selection."}), 400

            normalized_event_path = Path(raw_event_path.strip())
            if normalized_event_path in {Path("."), Path("")}:
                return jsonify({"error": "Deleting the TeslaCam root is not allowed."}), 400

            event_dir = frontend_module.resolve_path_within_footage_root(footage_root, str(normalized_event_path))
            if not event_dir.is_dir():
                return jsonify({"error": f"Clip folder not found: {raw_event_path}"}), 404

            if event_dir in seen_directories:
                continue

            seen_directories.add(event_dir)
            event_directories.append(event_dir)
            deleted_paths.append(str(normalized_event_path))

        for event_dir in event_directories:
            try:
                shutil.rmtree(event_dir)
            except OSError:
                return jsonify({"error": f"Could not delete {event_dir.name}."}), 500

        frontend_module.clear_event_summary_cache()
        return jsonify({"deletedPaths": deleted_paths})

    @app.post("/events/<path:event_path>/player-edits")
    def update_event_player_edits(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.resolve_path_within_footage_root(footage_root, event_path)
        if not event_dir.is_dir():
            return jsonify({"error": "Clip folder not found."}), 404

        if not frontend_module.is_event_indexed(event_dir):
            frontend_module.queue_event_processing(event_dir)
            return jsonify({"error": "Clip indexing is still in progress."}), 409

        payload = request.get_json(silent=True)
        player_edits = frontend_module.normalize_saved_player_edits(payload)
        if player_edits is None:
            return jsonify({"error": "Invalid player edits request."}), 400

        processing_state = frontend_module.load_event_processing_state(event_dir)
        processing_state["playerEdits"] = player_edits
        processing_state["normalizedEditSegments"] = frontend_module.get_normalized_edit_segments(event_path, player_edits)
        try:
            frontend_module.write_event_processing_state(event_dir, processing_state)
        except OSError:
            return jsonify({"error": "Could not save player edits."}), 500

        return jsonify({
            "playerEdits": player_edits,
            "normalizedEditSegments": processing_state["normalizedEditSegments"],
        })

    @app.post("/events/<path:event_path>/render")
    def render_event_export(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.resolve_path_within_footage_root(footage_root, event_path)
        if not event_dir.is_dir():
            return jsonify({"error": "Clip folder not found."}), 404

        if not frontend_module.is_event_indexed(event_dir):
            frontend_module.queue_event_processing(event_dir)
            return jsonify({"error": "Clip indexing is still in progress."}), 409

        processing_state = frontend_module.load_event_processing_state(event_dir)
        payload = request.get_json(silent=True)
        requested_profile = None
        player_edits = None
        if isinstance(payload, dict):
            raw_profile = payload.get("outputProfile")
            if isinstance(raw_profile, str):
                requested_profile = raw_profile
            player_edits = frontend_module.normalize_saved_player_edits(payload.get("playerEdits"))

        if player_edits is None:
            player_edits = frontend_module.get_saved_player_edits(processing_state)
        if player_edits is None:
            return jsonify({"error": "No saved player edits are available for export yet."}), 400

        processing_state["playerEdits"] = player_edits
        processing_state["normalizedEditSegments"] = frontend_module.get_normalized_edit_segments(event_path, player_edits)
        try:
            frontend_module.write_event_processing_state(event_dir, processing_state)
        except OSError:
            return jsonify({"error": "Could not save render request state."}), 500

        active_render_job = frontend_module.get_latest_event_render_job(
            footage_root,
            event_path,
            statuses=frontend_module.ACTIVE_JOB_STATUSES,
        )
        if active_render_job is not None:
            return jsonify({"job": frontend_module.serialize_render_job(event_path, active_render_job)}), 202

        output_profile = _resolve_output_profile(frontend_module, requested_profile, player_edits)
        job = frontend_module.enqueue_render_job(
            footage_root=footage_root,
            event_id=event_path,
            player_edits=player_edits,
            output_profile=output_profile,
        )

        return jsonify({"job": frontend_module.serialize_render_job(event_path, job)}), 202

    @app.get("/events/<path:event_path>/render/jobs/<job_id>")
    def get_render_job_status(event_path: str, job_id: str):
        footage_root = frontend_module.get_footage_root(app)
        job = frontend_module.get_render_job(footage_root, job_id)
        if job is None or job.get("eventId") != event_path:
            return jsonify({"error": "Render job not found."}), 404
        return jsonify({"job": frontend_module.serialize_render_job(event_path, job)})

    @app.get("/events/<path:event_path>/render/latest")
    def download_latest_event_render(event_path: str):
        footage_root = frontend_module.get_footage_root(app)
        event_dir = frontend_module.require_event_dir(footage_root, event_path)

        latest_render = frontend_module.get_latest_render_metadata(event_dir)
        if latest_render is None:
            abort(404)

        output_path = Path(str(latest_render["outputPath"])).resolve()
        if not output_path.is_file() or not frontend_module._is_within_root(output_path, footage_root):
            abort(404)

        return send_file(
            output_path,
            as_attachment=True,
            download_name=str(latest_render.get("downloadFileName") or output_path.name),
            conditional=True,
        )


def _resolve_output_profile(
    frontend_module: ModuleType,
    requested_profile: str | None,
    player_edits: dict[str, object],
) -> str:
    if isinstance(requested_profile, str) and requested_profile in frontend_module.EXPORT_FORMAT_OPTIONS:
        return requested_profile
    return str(player_edits.get("exportFormat") or "4k")
