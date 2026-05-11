"""Demo API routes with rate limiting."""

from flask import Blueprint, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from src.demo.helpers import get_demo_datasets, get_demo_query_results
from config import limiter

routes = Blueprint("demo", __name__, url_prefix="/api/demo")


# Apply rate limiting to specific endpoints
@routes.route("/datasets", methods=["GET"])
@limiter.limit("100 per hour")
def list_datasets():
    """Return list of demo datasets."""
    try:
        datasets = get_demo_datasets()
        return jsonify({"datasets": datasets, "count": len(datasets)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@routes.route("/query", methods=["GET"])
@limiter.limit("100 per hour")
def query_data():
    """Execute demo query with parameters."""
    dataset = request.args.get("dataset", "gut_microbiome")
    group_by = request.args.get("group_by", "organism")
    measure = request.args.get("measure", "abundance")

    try:
        results = get_demo_query_results(dataset, group_by, measure)
        return jsonify({"dataset": dataset, "group_by": group_by, "measure": measure, "results": results})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@routes.route("/health", methods=["GET"])
def health_check():
    """Health check for demo API."""
    return jsonify({"status": "healthy", "service": "demo-api"})