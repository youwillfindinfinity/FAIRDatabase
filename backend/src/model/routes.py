"""
routes.py — Flask blueprint for the lifetime PBPK model.

Registered in app.py with url_prefix="/model".

Endpoints
---------
GET  /model/ui                        Renders the simulation UI (login required)
POST /model/run                       Runs one scenario in-memory, returns JSON
GET  /model/scenarios                 Returns available scenario list as JSON
POST /model/parameter-sets            Store a named parameter set
GET  /model/parameter-sets            List all public parameter sets
GET  /model/parameter-sets/<id>       Fetch one parameter set with full params
"""
from __future__ import annotations

import os
import tempfile
import uuid as _uuid

from flask import Blueprint, abort, g, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

from config import supabase_extension
from src.auth.decorators import login_required
from .helpers import (
    run_scenario,
    available_scenarios,
    store_parameter_set,
    fetch_parameter_set,
    list_parameter_sets,
    create_run,
    update_run,
    fetch_run,
    assert_can_read_run,
    assert_can_modify_run,
    insert_artifact,
    list_artifacts,
    fetch_artifact,
    delete_artifact_row,
    DEFAULT_PARAMS,
)

# ── Artifact upload config ────────────────────────────────────────────────────
ARTIFACT_BUCKET = "pbpk-artifacts"
ARTIFACT_MAX_BYTES = 200 * 1024 * 1024  # 200 MB
ARTIFACT_SIGNED_URL_TTL = 60 * 10        # 10 minutes
ARTIFACT_CHUNK_BYTES = 1 * 1024 * 1024   # 1 MB stream chunks

# mime -> (kind, allowed extensions) — vtk has no registered MIME so we accept
# octet-stream + extension match.
_ARTIFACT_TYPES = {
    "image/jpeg": ("image", {".jpg", ".jpeg"}),
    "image/png":  ("image", {".png"}),
    "video/mp4":  ("video", {".mp4"}),
    "application/octet-stream": ("mesh", {".vtk", ".vtu", ".vtp"}),
}


def _classify_artifact(mime: str, filename: str) -> tuple[str, str]:
    """Return (kind, normalized_mime) or raise ValueError."""
    ext = os.path.splitext(filename)[1].lower()
    mime = (mime or "").lower()
    if mime in _ARTIFACT_TYPES:
        kind, exts = _ARTIFACT_TYPES[mime]
        if ext not in exts:
            raise ValueError(f"extension {ext!r} does not match mime {mime!r}")
        return kind, mime
    if ext in {".vtk", ".vtu", ".vtp"}:
        return "mesh", "application/octet-stream"
    raise ValueError(f"unsupported artifact type: mime={mime!r} ext={ext!r}")

routes = Blueprint("model_routes", __name__)


# ── Existing endpoints ────────────────────────────────────────────────────────

@routes.route("/ui", methods=["GET"])
@login_required()
def model_ui():
    role = getattr(g, "role", None)
    return render_template(
        "model/pbkfair.html",
        scenarios=available_scenarios(),
        user_email=session.get("email"),
        current_user_id=getattr(g, "user", None),
        is_admin=(role == "admin"),
        can_upload=role in ("admin", "curator"),
        can_view_artifacts=role in ("admin", "curator", "accessor"),
        current_path=request.path,
    )


@routes.route("/run", methods=["POST"])
@login_required()
def run():
    payload = request.get_json(silent=True) or {}
    try:
        result = run_scenario(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": f"Simulation failed: {exc}"}), 500
    return jsonify(result), 200


@routes.route("/scenarios", methods=["GET"])
@login_required()
def scenarios():
    return jsonify(available_scenarios()), 200


# ── Parameter set endpoints ───────────────────────────────────────────────────

@routes.route("/parameter-sets", methods=["POST"])
@login_required("admin", "curator")
def create_parameter_set():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    params = payload.get("params", {})
    if not isinstance(params, dict):
        return jsonify({"error": "params must be a JSON object"}), 400
    description = payload.get("description", "")
    created_by = session.get("email", "")
    ps_id = store_parameter_set(name, description, params, created_by, owner_id=g.user)
    return jsonify({"id": ps_id, "name": name}), 201


@routes.route("/parameter-sets", methods=["GET"])
@login_required()
def get_parameter_sets():
    return jsonify(list_parameter_sets()), 200


@routes.route("/parameter-sets/<int:param_set_id>", methods=["GET"])
@login_required()
def get_parameter_set(param_set_id):
    ps = fetch_parameter_set(param_set_id)
    if ps is None:
        return jsonify({"error": "Parameter set not found"}), 404
    return jsonify(ps), 200


# ── Simulation run endpoints ──────────────────────────────────────────────────

@routes.route("/runs", methods=["POST"])
@login_required("admin", "curator")
def create_simulation_run():
    payload = request.get_json(silent=True) or {}
    param_set_id = payload.get("param_set_id")
    if param_set_id is None:
        return jsonify({"error": "param_set_id is required"}), 400

    ps = fetch_parameter_set(int(param_set_id))
    if ps is None:
        return jsonify({"error": "Parameter set not found"}), 404

    scenario = payload.get("scenario", "no_bf")
    created_by = session.get("email", "")

    run_id = create_run(int(param_set_id), scenario, created_by, owner_id=g.user)
    update_run(run_id, "running")

    merged_params = {**DEFAULT_PARAMS, **ps["params"], "scenario": scenario}

    try:
        result = run_scenario(merged_params)
    except ValueError as exc:
        update_run(run_id, "error", error_message=str(exc))
        return jsonify({"error": str(exc), "run_id": run_id}), 400
    except RuntimeError as exc:
        update_run(run_id, "error", error_message=str(exc))
        return jsonify({"error": f"Simulation failed: {exc}", "run_id": run_id}), 500

    summary = {
        "peak_C_ven": result.get("peak_C_ven"),
        "peak_Age_yr": result.get("peak_Age_yr"),
        "final_C_ven": result.get("final_C_ven"),
        "final_Age_yr": result.get("final_Age_yr"),
        "n_rows": result.get("n_rows"),
    }
    update_run(run_id, "done", summary=summary, timeseries=result.get("timeseries"))

    return jsonify({"run_id": run_id, **result}), 200


@routes.route("/runs/<int:run_id>", methods=["GET"])
@login_required("admin", "curator", "accessor")
def get_simulation_run(run_id):
    cur = g.db.cursor()
    try:
        assert_can_read_run(cur, run_id, g.user, g.role)
    except FileNotFoundError:
        return jsonify({"error": "Run not found"}), 404
    except PermissionError:
        abort(403)
    finally:
        cur.close()
    run = fetch_run(run_id)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(run), 200


# ── Artifact endpoints (PoC) ──────────────────────────────────────────────────
#
# Bytes live in Supabase Storage bucket ``pbpk-artifacts``; this app only
# manages the catalog row in _fd.pbpk_run_artifacts and short-lived signed
# URLs. Bucket + storage.objects policies must be created in Supabase
# (see CLAUDE.md PBPK section).

def _signed_url(storage_path: str) -> str | None:
    """Return a short-lived signed URL for ``storage_path`` or None on failure.

    storage_path is stored as ``<bucket>/<object key>``; the Supabase SDK
    expects bucket + key separately.
    """
    try:
        bucket, _, key = storage_path.partition("/")
        if not bucket or not key:
            return None
        resp = supabase_extension.client.storage.from_(bucket).create_signed_url(
            key, ARTIFACT_SIGNED_URL_TTL
        )
        return resp.get("signedURL") or resp.get("signed_url")
    except Exception:
        return None


@routes.route("/runs/<int:run_id>/artifacts", methods=["POST"])
@login_required("admin", "curator")
def upload_run_artifact(run_id):
    cur = g.db.cursor()
    try:
        assert_can_modify_run(cur, run_id, g.user, g.role)
    except FileNotFoundError:
        return jsonify({"error": "Run not found"}), 404
    except PermissionError:
        abort(403)
    finally:
        cur.close()

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "file is required (multipart field 'file')"}), 400

    safe_name = secure_filename(file.filename)
    if not safe_name:
        return jsonify({"error": "invalid filename"}), 400

    try:
        kind, mime = _classify_artifact(file.mimetype, safe_name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Stream the upload to a tempfile in fixed-size chunks instead of calling
    # file.read() (which would materialize up to ARTIFACT_MAX_BYTES in RAM per
    # concurrent upload). Werkzeug already spools the request body to disk for
    # large uploads, but reading it back into a single bytes object defeats
    # that. Peak RAM here is one chunk per worker.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(safe_name)[1])
    tmp_path = tmp.name
    size = 0
    try:
        try:
            while True:
                chunk = file.stream.read(ARTIFACT_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > ARTIFACT_MAX_BYTES:
                    return jsonify({
                        "error": f"file exceeds {ARTIFACT_MAX_BYTES} byte limit"
                    }), 413
                tmp.write(chunk)
        finally:
            tmp.close()

        if size == 0:
            return jsonify({"error": "empty file"}), 400

        object_key = f"run_{run_id}/{_uuid.uuid4().hex}_{safe_name}"
        storage_path = f"{ARTIFACT_BUCKET}/{object_key}"

        try:
            with open(tmp_path, "rb") as fh:
                supabase_extension.client.storage.from_(ARTIFACT_BUCKET).upload(
                    object_key,
                    fh,
                    file_options={"content-type": mime, "upsert": "false"},
                )
        except Exception as exc:
            return jsonify({"error": f"storage upload failed: {exc}"}), 502

        try:
            artifact_id = insert_artifact(
                run_id=run_id,
                owner_id=g.user,
                kind=kind,
                storage_path=storage_path,
                mime=mime,
                size_bytes=size,
                original_name=safe_name,
            )
        except Exception as exc:
            # Best-effort cleanup so we don't leak orphan blobs.
            try:
                supabase_extension.client.storage.from_(ARTIFACT_BUCKET).remove([object_key])
            except Exception:
                pass
            return jsonify({"error": f"catalog insert failed: {exc}"}), 500

        return jsonify({
            "id": artifact_id,
            "run_id": run_id,
            "kind": kind,
            "mime": mime,
            "size_bytes": size,
            "original_name": safe_name,
            "storage_path": storage_path,
            "url": _signed_url(storage_path),
        }), 201
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@routes.route("/runs/<int:run_id>/artifacts", methods=["GET"])
@login_required("admin", "curator", "accessor")
def list_run_artifacts(run_id):
    cur = g.db.cursor()
    try:
        assert_can_read_run(cur, run_id, g.user, g.role)
    except FileNotFoundError:
        return jsonify({"error": "Run not found"}), 404
    except PermissionError:
        abort(403)
    finally:
        cur.close()

    rows = list_artifacts(run_id)
    for r in rows:
        r["url"] = _signed_url(r["storage_path"])
    return jsonify(rows), 200


@routes.route("/artifacts/<int:artifact_id>", methods=["DELETE"])
@login_required("admin", "curator")
def delete_run_artifact(artifact_id):
    artifact = fetch_artifact(artifact_id)
    if artifact is None:
        return jsonify({"error": "Artifact not found"}), 404

    if g.role != "admin" and str(artifact["owner_id"]) != str(g.user):
        abort(403)

    bucket, _, key = artifact["storage_path"].partition("/")
    try:
        supabase_extension.client.storage.from_(bucket).remove([key])
    except Exception:
        # Don't block catalog cleanup on a missing blob; log via response.
        pass

    delete_artifact_row(artifact_id)
    return jsonify({"deleted": artifact_id}), 200
