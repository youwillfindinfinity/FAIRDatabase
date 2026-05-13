"""
routes.py — FL blueprint.

/federated/ui              GET  — FL dashboard UI (login required)
/fl/tasks                  POST — Create FL task
/fl/tasks/<id>             GET  — Task status
/fl/tasks/<id>/rounds      GET  — List rounds
/fl/tasks/<id>/rounds/<n>/gradients  POST — Submit encrypted client update
/fl/tasks/<id>/model       GET  — Latest aggregated weights
/fl/tasks/<id>/export-params POST — Export weights as PBPK parameter set
"""
import json
import os
import numpy as np
from flask import (
    Blueprint, g, jsonify, redirect, render_template, request, session, url_for
)

from src.auth.decorators import login_required
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent
from src.federated.crypto import decrypt_weights
from src.federated.engine import (
    TabularMLP, get_flat_weights, set_flat_weights,
    local_train_fedprox, fedprox_aggregate, dirichlet_partition,
)
from src.federated import db as fl_db
from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp

routes = Blueprint("federated_routes", __name__)

import logging as _logging

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
if SECRET_KEY == "dev-secret":
    _logging.getLogger(__name__).warning(
        "SECRET_KEY is using the insecure dev default — "
        "set SECRET_KEY env var before deploying FL in production"
    )

# ── Legacy redirect ────────────────────────────────────────────────────────────

@routes.route("/federated_learning/federated_learning")
def legacy_federated_redirect():
    return redirect(url_for("federated_routes.federated_ui"), 301)


# ── UI ─────────────────────────────────────────────────────────────────────────

@routes.route("/ui", methods=["GET"])
@login_required()
def federated_ui():
    tasks = []
    try:
        with g.db.cursor() as cur:
            cur.execute("SELECT id, status, rounds_total, rounds_done, algorithm, dp_epsilon, simulation FROM _fd.fl_tasks ORDER BY created_at DESC LIMIT 20")
            cols = [d[0] for d in cur.description]
            tasks = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        g.db.rollback()
    return render_template(
        "federated_learning/federated_learning.html",
        tasks=tasks,
        user_email=session.get("email"),
        current_path=request.path,
    )


# ── Task endpoints ─────────────────────────────────────────────────────────────

@routes.route("/tasks", methods=["POST"])
@login_required("admin", "curator")
def create_task():
    payload = request.get_json(silent=True) or {}
    required = {"dp_epsilon", "rounds_total"}
    missing = required - set(payload)
    if missing:
        return jsonify({"error": f"Missing fields: {sorted(missing)}"}), 400

    dp_epsilon = float(payload["dp_epsilon"])
    dp_delta = float(payload.get("dp_delta", 1e-5))
    rounds_total = int(payload["rounds_total"])

    noise_mult = compute_noise_multiplier(
        epsilon=dp_epsilon, delta=dp_delta, rounds=rounds_total
    )

    task_id = fl_db.create_task(
        g.db,
        algorithm=payload.get("algorithm", "fedprox"),
        rounds_total=rounds_total,
        mu=float(payload.get("mu", 0.01)),
        dp_epsilon=dp_epsilon,
        dp_delta=dp_delta,
        dp_noise_mult=noise_mult,
        dp_clip_norm=float(payload.get("dp_clip_norm", 1.0)),
        simulation=bool(payload.get("simulation", False)),
        sim_alpha=float(payload.get("sim_alpha", 0.5)),
        sim_n_clients=int(payload.get("sim_n_clients", 5)),
        model_arch=payload.get("model_arch", {}),
        created_by=g.user,
    )
    return jsonify({"task_id": task_id, "dp_noise_mult": noise_mult}), 201


@routes.route("/tasks/<task_id>", methods=["GET"])
@login_required()
def get_task(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task), 200


@routes.route("/tasks/<task_id>/rounds", methods=["GET"])
@login_required()
def list_rounds(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    rounds = fl_db.list_rounds(g.db, task_id)
    # Strip raw weights from response — never expose to clients
    for r in rounds:
        r.pop("aggregated_weights", None)
    return jsonify(rounds), 200


@routes.route("/tasks/<task_id>/rounds/<int:round_n>/gradients", methods=["POST"])
@login_required("admin", "curator")
def submit_gradients(task_id, round_n):
    """
    Accept an encrypted client weight update, decrypt in memory,
    clip to L2 norm, add Gaussian DP noise, and aggregate.
    """
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404

    payload = request.get_json(silent=True) or {}
    if "ciphertext" not in payload or "nonce" not in payload:
        return jsonify({"error": "Encrypted gradient payload required"}), 400

    # Check epsilon budget for this dataset
    dataset_id = payload.get("dataset_id")
    if dataset_id:
        budget = fl_db.get_epsilon_budget(g.db, dataset_id)
        if budget and (budget["spent"] >= budget["total_budget"]):
            return jsonify({"error": "Epsilon budget exhausted for this dataset"}), 403

    # Decrypt in memory — never written to disk
    weights = decrypt_weights(payload, task_id, SECRET_KEY)

    # DP pipeline: clip → noise
    clip_norm = float(task["dp_clip_norm"])
    noise_mult = float(task["dp_noise_mult"])
    clipped = clip_gradients(weights, clip_norm)
    noised = add_gaussian_noise_dp(clipped, noise_mult, clip_norm)

    # Open or get current round
    rnd = fl_db.get_round(g.db, task_id, round_n)
    if rnd is None:
        fl_db.create_round(g.db, task_id, round_n)

    # Accumulate into round — fetch existing aggregated weights if present
    rnd = fl_db.get_round(g.db, task_id, round_n)
    existing = rnd.get("aggregated_weights") or []
    existing_count = rnd.get("client_count", 0)

    # Running weighted sum (will be divided on aggregation trigger)
    if existing:
        acc = np.array(existing, dtype=np.float32) + noised
    else:
        acc = noised.copy()
    new_count = existing_count + 1

    # Check if all expected clients have submitted
    clients_needed = int(task.get("sim_n_clients", 1))
    is_final = new_count >= clients_needed

    if is_final:
        # Divide accumulated sum by client count to get average
        aggregated = (acc / new_count).tolist()
        eps_spent = compute_epsilon_spent(
            noise_multiplier=noise_mult,
            delta=float(task["dp_delta"]),
            rounds_done=int(task["rounds_done"]) + 1,
        )
        fl_db.store_aggregated_weights(g.db, task_id, round_n,
                                        aggregated, eps_spent, None)
        fl_db.advance_task_round(g.db, task_id)

        if dataset_id:
            fl_db.consume_epsilon(g.db, dataset_id, eps_spent)

        if int(task["rounds_done"]) + 1 >= int(task["rounds_total"]):
            fl_db.set_task_status(g.db, task_id, "completed")
    else:
        # Store intermediate accumulation back into round
        with g.db.cursor() as cur:
            cur.execute(
                "UPDATE _fd.fl_rounds SET aggregated_weights=%s, client_count=%s WHERE task_id=%s AND round_n=%s",
                (json.dumps(acc.tolist()), new_count, task_id, round_n),
            )
        g.db.commit()

    return jsonify({"status": "accepted", "round": round_n, "clients": new_count}), 200


@routes.route("/tasks/<task_id>/model", methods=["GET"])
@login_required()
def get_model(task_id):
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    weights = fl_db.get_latest_weights(g.db, task_id)
    if weights is None:
        return jsonify({"error": "No completed round yet"}), 404
    return jsonify({"task_id": task_id, "weights": weights}), 200


@routes.route("/tasks/<task_id>/export-params", methods=["POST"])
@login_required("admin", "curator")
def export_params(task_id):
    """Export final aggregated FL weights as a named PBPK parameter set."""
    from src.model.helpers import store_parameter_set
    task = fl_db.get_task(g.db, task_id)
    if task is None:
        return jsonify({"error": "Task not found"}), 404
    weights = fl_db.get_latest_weights(g.db, task_id)
    if weights is None:
        return jsonify({"error": "No model to export yet"}), 404

    payload = request.get_json(silent=True) or {}
    name = payload.get("name", f"FL-task-{task_id[:8]}")
    description = payload.get("description", f"Federated learning aggregated weights (task {task_id})")

    ps_id = store_parameter_set(
        name=name,
        description=description,
        params={"fl_weights": weights, "fl_task_id": task_id},
        created_by=session.get("email", ""),
        owner_id=g.user,
        source="federated",
    )

    # Purge raw weights from DB after export (privacy hygiene)
    fl_db.purge_round_weights(g.db, task_id)

    return jsonify({"parameter_set_id": ps_id, "name": name}), 201


# ── Second registration point for /fl/ prefix ─────────────────────────────────

fl_routes = Blueprint("fl_routes", __name__)
fl_routes.add_url_rule("/tasks", view_func=create_task, methods=["POST"])
fl_routes.add_url_rule("/tasks/<task_id>", view_func=get_task, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/rounds", view_func=list_rounds, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/rounds/<int:round_n>/gradients",
                        view_func=submit_gradients, methods=["POST"])
fl_routes.add_url_rule("/tasks/<task_id>/model", view_func=get_model, methods=["GET"])
fl_routes.add_url_rule("/tasks/<task_id>/export-params",
                        view_func=export_params, methods=["POST"])
