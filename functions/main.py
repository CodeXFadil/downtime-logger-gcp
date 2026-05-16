import json
import os
import uuid
from datetime import datetime, timezone

import functions_framework
from google.cloud import storage

GCS_BUCKET = os.environ["GCS_BUCKET"]
SITE_NAME  = os.environ.get("SITE_NAME", "Unknown")
REGION_KEY = os.environ.get("REGION_KEY", "unknown")

SHIFTS = ["Morning", "Afternoon", "Night"]


def _json(data, status=200):
    from flask import Response
    return Response(json.dumps(data), status=status, mimetype="application/json")


def _bucket():
    return storage.Client().bucket(GCS_BUCKET)


@functions_framework.http
def health(request):
    return _json({"status": "healthy", "site": SITE_NAME, "region": REGION_KEY})


@functions_framework.http
def master_data(request):
    try:
        bucket = _bucket()
        all_equipment = json.loads(bucket.blob("master/equipment.json").download_as_text())
        reasons       = json.loads(bucket.blob("master/reasons.json").download_as_text())
        equipment = [
            {"id": e["id"], "name": e["name"]}
            for e in all_equipment
            if e["site"] == SITE_NAME
        ]
        return _json({"equipment": equipment, "reasons": reasons, "shifts": SHIFTS})
    except Exception as exc:
        return _json({"error": str(exc)}, 500)


@functions_framework.http
def records(request):
    try:
        bucket = _bucket()
        blobs = sorted(
            bucket.list_blobs(prefix=f"records/{REGION_KEY}/"),
            key=lambda b: b.name,
            reverse=True,
        )[:50]
        return _json([json.loads(b.download_as_text()) for b in blobs])
    except Exception as exc:
        return _json({"error": str(exc)}, 500)


@functions_framework.http
def submit(request):
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
