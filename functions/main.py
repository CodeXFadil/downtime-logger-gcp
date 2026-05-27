import json
import os
import uuid
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_functions import https_fn
from google.cloud import storage

GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
SITE_NAME  = os.environ.get("SITE_NAME", "Unknown")
REGION_KEY = os.environ.get("REGION_KEY", "unknown")
SHIFTS     = ["Morning", "Afternoon", "Night"]

firebase_admin.initialize_app()


def _json(data, status=200):
    from flask import Response
    resp = Response(json.dumps(data), status=status, mimetype="application/json")
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Firebase-Token"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _verify_token(request):
    # X-Firebase-Token set by demo_server.py (Authorization is used for Cloud Run IAM there)
    # Authorization used directly when Firebase Hosting proxies the request
    token = request.headers.get("X-Firebase-Token", "").strip()
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
    try:
        return fb_auth.verify_id_token(token)
    except Exception:
        return None


def _bucket():
    return storage.Client().bucket(GCS_BUCKET)


@https_fn.on_request(region="us-central1")
def health(request: https_fn.Request) -> https_fn.Response:
    if request.method == "OPTIONS":
        return _json({})
    return _json({"status": "healthy", "site": SITE_NAME, "region": REGION_KEY})


@https_fn.on_request(region="us-central1")
def master_data(request: https_fn.Request) -> https_fn.Response:
    if request.method == "OPTIONS":
        return _json({})
    if not _verify_token(request):
        return _json({"error": "Unauthorized"}, 401)
    try:
        bucket        = _bucket()
        all_equipment = json.loads(bucket.blob("master/equipment.json").download_as_text())
        reasons       = json.loads(bucket.blob("master/reasons.json").download_as_text())
        equipment     = [
            {"id": e["id"], "name": e["name"]}
            for e in all_equipment
            if e["site"] == SITE_NAME
        ]
        return _json({"equipment": equipment, "reasons": reasons, "shifts": SHIFTS})
    except Exception as exc:
        return _json({"error": str(exc)}, 500)


@https_fn.on_request(region="us-central1")
def records(request: https_fn.Request) -> https_fn.Response:
    if request.method == "OPTIONS":
        return _json({})
    if not _verify_token(request):
        return _json({"error": "Unauthorized"}, 401)
    try:
        bucket = _bucket()
        blobs  = sorted(
            bucket.list_blobs(prefix=f"records/{REGION_KEY}/"),
            key=lambda b: b.name,
            reverse=True,
        )[:50]
        return _json([json.loads(b.download_as_text()) for b in blobs])
    except Exception as exc:
        return _json({"error": str(exc)}, 500)


@https_fn.on_request(region="us-central1")
def submit(request: https_fn.Request) -> https_fn.Response:
    if request.method == "OPTIONS":
        return _json({})
    if not _verify_token(request):
        return _json({"error": "Unauthorized"}, 401)
    body = request.get_json(silent=True)
    if not body:
        return _json({"error": "Invalid JSON"}, 400)
    for field in ("equipment_id", "reason", "duration_minutes", "category"):
        if not body.get(field) and body.get(field) != 0:
            return _json({"error": f"Missing required field: {field}"}, 400)
    try:
        record_id = str(uuid.uuid4())
        now       = datetime.now(timezone.utc).isoformat()
        record    = {
            "id":               record_id,
            "site":             SITE_NAME,
            "equipment_id":     body["equipment_id"],
            "reason":           body["reason"],
            "duration_minutes": int(body["duration_minutes"]),
            "category":         body["category"],
            "shift":            body.get("shift", ""),
            "operator_name":    body.get("operator_name", ""),
            "notes":            body.get("notes", ""),
            "start_time":       now,
        }
        blob_name = f"records/{REGION_KEY}/{now[:19].replace(':', '-')}-{record_id}.json"
        _bucket().blob(blob_name).upload_from_string(
            json.dumps(record), content_type="application/json"
        )
        return _json({"id": record_id, "site": SITE_NAME})
    except Exception as exc:
        return _json({"error": str(exc)}, 500)
