import json
import os
from contextlib import contextmanager

import functions_framework
import pg8000.native

DB_HOST     = os.environ["DB_HOST"]
DB_NAME     = os.environ.get("DB_NAME", "downtime-db")
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
SITE_NAME   = os.environ.get("SITE_NAME", "Unknown")
REGION_KEY  = os.environ.get("REGION_KEY", "unknown")

SHIFTS = ["Morning", "Afternoon", "Night"]


def _json(data, status=200):
    from flask import Response
    return Response(json.dumps(data), status=status, mimetype="application/json")


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
    return _json({
        "status": "healthy",
        "site":   SITE_NAME,
        "region": REGION_KEY,
        "db":     DB_HOST,
    })


@functions_framework.http
def master_data(request):
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
        return _json({"equipment": equipment, "reasons": reasons, "shifts": SHIFTS})
    except Exception as exc:
        return _json({"error": str(exc)}, status=500)


@functions_framework.http
def records(request):
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
        return _json([{cols[i]: row[i] for i in range(len(cols))} for row in rows])
    except Exception as exc:
        return _json({"error": str(exc)}, status=500)


@functions_framework.http
def submit(request):
    body = request.get_json(silent=True)
    if not body:
        return _json({"detail": "Invalid JSON"}, status=400)

    for field in ("equipment_id", "reason", "duration_minutes", "category"):
        if not body.get(field) and body.get(field) != 0:
            return _json({"detail": f"Missing required field: {field}"}, status=400)

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
        return _json({"status": "saved", "id": new_id, "site": SITE_NAME})
    except Exception as exc:
        return _json({"detail": str(exc)}, status=500)
