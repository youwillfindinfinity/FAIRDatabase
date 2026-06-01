"""Routes for bundled FAIR PBPK study models.

Attached to the pbpk plugin's main Blueprint (see ``routes.py``). Endpoints are
mounted under ``/model/studies/<slug>/`` once the parent blueprint is registered
at ``url_prefix=/model``.

The heavy ``libsbml``/``scipy`` dependencies pulled in by the runners are
imported lazily through :mod:`plugins.pbpk.studies` so plugin discovery and
the rest of the pbpk routes keep working without them installed.
"""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from kernel.auth import login_required

from . import studies as _studies


def _meta(slug: str):
    meta = _studies.STUDIES.get(slug)
    if meta is None:
        abort(404, description=f"Unknown study '{slug}'")
    return meta


def _scenarios(mod) -> list[dict]:
    return [
        {"label": s["label"], "description": s["description"]}
        for s in getattr(mod, "SCENARIOS", [])
    ]


def _compounds(mod) -> list[dict]:
    return [
        {"label": c["label"], "description": c["description"]}
        for c in getattr(mod, "COMPOUNDS", [])
    ]


def register(routes):
    """Attach study endpoints to the given pbpk Blueprint."""

    @routes.route("/studies", methods=["GET"])
    @login_required()
    def studies_index():
        return jsonify([
            {"slug": m["slug"], "label": m["label"]}
            for m in _studies.STUDIES.values()
        ]), 200

    @routes.route("/studies/<slug>/ui", methods=["GET"])
    @login_required()
    def study_ui(slug):
        meta = _meta(slug)
        try:
            mod = _studies.load(slug)
        except ImportError as exc:
            return (
                f"Study '{slug}' is unavailable: missing dependency ({exc}).",
                503,
            )
        ctx = {
            "user_email": session.get("email"),
            "current_path": request.path,
            "slug": slug,
            "pbpk_active_tab": slug,
        }
        if meta["has_scenarios"]:
            ctx["scenarios"] = _scenarios(mod)
        if meta["has_compounds"]:
            ctx["compounds"] = _compounds(mod)
        return render_template(meta["template"], **ctx)

    @routes.route("/studies/<slug>/run", methods=["POST"])
    @login_required()
    def study_run(slug):
        _meta(slug)
        try:
            mod = _studies.load(slug)
        except ImportError as exc:
            return jsonify({"error": f"Study unavailable: {exc}"}), 503
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(mod.execute(payload)), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": f"Simulation failed: {exc}"}), 500

    @routes.route("/studies/<slug>/scenarios", methods=["GET"])
    @login_required()
    def study_scenarios(slug):
        meta = _meta(slug)
        if not meta["has_scenarios"]:
            return jsonify([]), 200
        return jsonify(_scenarios(_studies.load(slug))), 200

    @routes.route("/studies/<slug>/compounds", methods=["GET"])
    @login_required()
    def study_compounds(slug):
        meta = _meta(slug)
        if not meta["has_compounds"]:
            return jsonify([]), 200
        return jsonify(_compounds(_studies.load(slug))), 200
