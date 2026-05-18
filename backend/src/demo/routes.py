"""Demo API routes with rate limiting."""

import logging

from flask import Blueprint, current_app, jsonify, request
from src.demo.helpers import get_demo_datasets, get_demo_query_results
from config import limiter

routes = Blueprint("demo", __name__, url_prefix="/api/demo")

_log = logging.getLogger(__name__)

# Rate limit read from config at request time (DEMO_RATE_LIMIT) rather than
# hardcoded, so it is tunable via env without code changes.
_rate_limit = lambda: current_app.config["DEMO_RATE_LIMIT"]


@routes.route("/datasets", methods=["GET"])
@limiter.limit(_rate_limit)
def list_datasets():
    """Return list of demo datasets."""
    try:
        datasets = get_demo_datasets()
        return jsonify({"datasets": datasets, "count": len(datasets)})
    except Exception:
        _log.exception("demo list_datasets failed")
        return jsonify({"error": "Internal error"}), 500


@routes.route("/query", methods=["GET"])
@limiter.limit(_rate_limit)
def query_data():
    """Execute demo query with parameters."""
    dataset = request.args.get("dataset", "gut_microbiome")
    group_by = request.args.get("group_by", "organism")
    measure = request.args.get("measure", "abundance")

    try:
        results = get_demo_query_results(dataset, group_by, measure)
        return jsonify({"dataset": dataset, "group_by": group_by, "measure": measure, "results": results})
    except ValueError as e:
        # Validation messages are safe to surface (no internal detail).
        return jsonify({"error": str(e)}), 400
    except Exception:
        _log.exception("demo query_data failed")
        return jsonify({"error": "Internal error"}), 500


@routes.route("/health", methods=["GET"])
def health_check():
    """Health check for demo API."""
    return jsonify({"status": "healthy", "service": "demo-api"})