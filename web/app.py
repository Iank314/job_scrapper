from datetime import datetime, timezone
from functools import wraps
import os
import sys

from flask import Flask, jsonify, render_template, request, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import APP_PASSWORD, APP_SECRET_KEY
from db import (
    get_all_jobs,
    get_applied_jobs,
    get_stats,
    get_trashed_jobs,
    mark_applied,
    mark_trashed,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = APP_SECRET_KEY
# Sessions last 30 days so you don't re-login every restart (unless
# APP_SECRET_KEY rotates, which it does when unset — set it to pin).
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30

if APP_PASSWORD == "changeme":
    print("[warn] APP_PASSWORD is set to the default 'changeme' — set APP_PASSWORD env var to something else.")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return jsonify({"error": "auth required"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth", methods=["GET"])
def api_auth_status():
    return jsonify({"authed": bool(session.get("authed"))})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if password == APP_PASSWORD:
        session.permanent = True
        session["authed"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "invalid password"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/jobs")
def api_jobs():
    category = request.args.get("category", "All")
    search = request.args.get("search", "").strip()
    active_only = request.args.get("active_only", "true") == "true"
    new_only = request.args.get("new_only", "false") == "true"

    since = None
    if new_only:
        since = session.get("last_seen_at")

    jobs = get_all_jobs(
        category=category,
        search=search or None,
        active_only=active_only,
        include_applied=False,
        since=since,
    )
    stats = get_stats()
    return jsonify({
        "jobs": jobs,
        "stats": stats,
        "authed": bool(session.get("authed")),
        "last_seen_at": session.get("last_seen_at"),
    })


@app.route("/api/mark-seen", methods=["POST"])
def api_mark_seen():
    """Update the 'last seen' timestamp to now. Called by the UI when the
    user opens the page or explicitly clears the 'new' filter."""
    session["last_seen_at"] = datetime.now(timezone.utc).isoformat()
    session.permanent = True
    return jsonify({"ok": True, "last_seen_at": session["last_seen_at"]})


@app.route("/api/jobs/applied")
@login_required
def api_applied_jobs():
    search = request.args.get("search", "").strip()
    jobs = get_applied_jobs(search=search or None)
    return jsonify({"jobs": jobs})


@app.route("/api/jobs/<int:job_id>/apply", methods=["POST"])
@login_required
def api_mark_applied(job_id):
    ok = mark_applied(job_id, applied=True)
    if not ok:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/unapply", methods=["POST"])
@login_required
def api_unmark_applied(job_id):
    ok = mark_applied(job_id, applied=False)
    if not ok:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/jobs/trashed")
@login_required
def api_trashed_jobs():
    search = request.args.get("search", "").strip()
    jobs = get_trashed_jobs(search=search or None)
    return jsonify({"jobs": jobs})


@app.route("/api/jobs/<int:job_id>/trash", methods=["POST"])
@login_required
def api_mark_trashed(job_id):
    ok = mark_trashed(job_id, trashed=True)
    if not ok:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/untrash", methods=["POST"])
@login_required
def api_unmark_trashed(job_id):
    ok = mark_trashed(job_id, trashed=False)
    if not ok:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})
