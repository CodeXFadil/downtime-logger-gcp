import json
import os
import time
from contextlib import contextmanager

import functions_framework
import pg8000.native
import jwt as pyjwt
import requests as http_requests

DB_HOST        = os.environ["DB_HOST"]
DB_NAME        = os.environ.get("DB_NAME", "downtime-db")
DB_USER        = os.environ["DB_USER"]
DB_PASSWORD    = os.environ["DB_PASSWORD"]
SITE_NAME      = os.environ.get("SITE_NAME", "Unknown")
REGION_KEY     = os.environ.get("REGION_KEY", "unknown")
PROJECT_ID     = os.environ.get("GOOGLE_CLOUD_PROJECT", "grace-np-dl-develop")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://grace-np-dl-develop.web.app")

SHIFTS = ["Morning", "Afternoon", "Night"]

_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
_certs_cache: dict = {"data": None, "expires": 0.0}


def _json(data, status=200):
    from flask import Response
    return Response(json.dumps(data), status=status, mimetype="application/json")


def _corsify(resp, request):
    origin = request.headers.get("Origin", "")
    allowed = {ALLOWED_ORIGIN, f"https://{PROJECT_ID}.firebaseapp.com"}
    resp.headers["Access-Control-Allow-Origin"] = origin if origin in allowed else ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Max-Age"] = "3600"
    return resp


def _firebase_certs():
    """Fetch and cache Google's Firebase signing certificates."""
    now = time.monotonic()
    if _certs_cache["data"] and now < _certs_cache["expires"]:
        return _certs_cache["data"]
    resp = http_requests.get(_CERTS_URL, timeout=5)
    resp.raise_for_status()
    max_age = 3600
    for part in resp.headers.get("Cache-Control", "").split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part[8:])
            except ValueError:
                pass
    _certs_cache["data"] = resp.json()
    _certs_cache["expires"] = now + max_age
    return _certs_cache["data"]


def _verify_token(request):
    """Return decoded Firebase JWT payload, or None if invalid/missing."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        kid = pyjwt.get_unverified_header(token).get("kid")
    except pyjwt.PyJWTError:
        return None
    cert = _firebase_certs().get(kid)
    if not cert:
        return None
    try:
        decoded = pyjwt.decode(
            token, cert,
            algorithms=["RS256"],
            audience=PROJECT_ID,
        )
    except pyjwt.PyJWTError:
        return None
    if decoded.get("iss") != f"https://securetoken.google.com/{PROJECT_ID}":
        return None
    return decoded


@contextmanager
def get_db():
    conn = pg8000.native.Connection(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        ssl_context=True,
    )
    try:
        yield conn
    finally:
        conn.close()


@functions_framework.http
def health(request):
    if request.method == "OPTIONS":
        return _corsify(_json({}), request)
    return _corsify(_json({
        "status": "healthy",
        "site":   SITE_NAME,
        "region": REGION_KEY,
        "db":     DB_HOST,
    }), request)


@functions_framework.http
def master_data(request):
    if request.method == "OPTIONS":
        return _corsify(_json({}), request)
    if not _verify_token(request):
        return _corsify(_json({"detail": "Unauthorized"}, status=401), request)
    try:
        with get_db() as conn:
            equipment = [
                {"id": r[0], "name": r[1]}
                for r in conn.run(
                    "SELECT equipment_id, display_name FROM Equipment "
                    "WHERE site_name = :site AND active = TRUE ORDER BY equipment_id",
                    site=SITE_NAME,
                )
            ]
            reasons = [
                {"name": r[0], "category": r[1]}
                for r in conn.run(
                    "SELECT reason_name, category FROM DowntimeReasons "
                    "WHERE active = TRUE ORDER BY category, reason_name"
                )
            ]
        return _corsify(
            _json({"equipment": equipment, "reasons": reasons, "shifts": SHIFTS}),
            request,
        )
    except Exception as exc:
        return _corsify(_json({"error": str(exc)}, status=500), request)


@functions_framework.http
def records(request):
    if request.method == "OPTIONS":
        return _corsify(_json({}), request)
    if not _verify_token(request):
        return _corsify(_json({"detail": "Unauthorized"}, status=401), request)
    try:
        with get_db() as conn:
            rows = conn.run(
                """
                SELECT id, site_name, equipment_id, reason,
                       duration_minutes,
                       TO_CHAR(start_time, 'YYYY-MM-DD HH24:MI:SS') AS start_time,
                       operator_name, category, shift
                FROM DowntimeRecords
                ORDER BY start_time DESC
                LIMIT 50
                """
            )
        cols = ["id", "site_name", "equipment_id", "reason",
                "duration_minutes", "start_time", "operator_name", "category", "shift"]
        return _corsify(
            _json([{cols[i]: row[i] for i in range(len(cols))} for row in rows]),
            request,
        )
    except Exception as exc:
        return _corsify(_json({"error": str(exc)}, status=500), request)


@functions_framework.http
def submit(request):
    if request.method == "OPTIONS":
        return _corsify(_json({}), request)
    if not _verify_token(request):
        return _corsify(_json({"detail": "Unauthorized"}, status=401), request)
    body = request.get_json(silent=True)
    if not body:
        return _corsify(_json({"detail": "Invalid JSON"}, status=400), request)

    for field in ("equipment_id", "reason", "duration_minutes", "category"):
        if not body.get(field) and body.get(field) != 0:
            return _corsify(
                _json({"detail": f"Missing required field: {field}"}, status=400),
                request,
            )

    try:
        with get_db() as conn:
            rows = conn.run(
                """
                INSERT INTO DowntimeRecords
                    (site_name, equipment_id, reason, duration_minutes,
                     operator_name, notes, category, shift)
                VALUES (:site, :equip, :reason, :duration,
                        :operator, :notes, :category, :shift)
                RETURNING id
                """,
                site=SITE_NAME,
                equip=body["equipment_id"],
                reason=body["reason"],
                duration=int(body["duration_minutes"]),
                operator=body.get("operator_name", ""),
                notes=body.get("notes", ""),
                category=body["category"],
                shift=body.get("shift", ""),
            )
            new_id = rows[0][0]
        return _corsify(
            _json({"status": "saved", "id": new_id, "site": SITE_NAME}),
            request,
        )
    except Exception as exc:
        return _corsify(_json({"detail": str(exc)}, status=500), request)
