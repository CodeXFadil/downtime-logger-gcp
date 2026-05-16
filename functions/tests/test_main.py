import base64
import json
import os
import azure.functions as func
from unittest.mock import patch, MagicMock

# Set required env vars before importing function_app
os.environ.setdefault("SQL_SERVER",   "test.database.windows.net")
os.environ.setdefault("SQL_USER",     "testuser")
os.environ.setdefault("SQL_PASSWORD", "testpass")
os.environ.setdefault("SQL_DATABASE", "downtime-db")
os.environ.setdefault("SITE_NAME",    "Curtis Bay")
os.environ.setdefault("REGION_KEY",   "us-north")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _principal_header(roles=None) -> str:
    """Build a base64-encoded X-MS-CLIENT-PRINCIPAL header for testing."""
    claims = [{"typ": "name", "val": "Test User"}]
    for role in (roles or []):
        claims.append({"typ": "roles", "val": role})
    payload = json.dumps({"claims": claims})
    return base64.b64encode(payload.encode()).decode()


OPERATOR_HEADERS = {
    "Content-Type":           "application/json",
    "X-MS-CLIENT-PRINCIPAL":  _principal_header(["Operator"]),
}

AUTH_HEADERS = {
    "Content-Type":           "application/json",
    "X-MS-CLIENT-PRINCIPAL":  _principal_header(),
}


# ── Request factory ───────────────────────────────────────────────────────────

def _make_req(method="GET", body=None, url="http://localhost/api/test", headers=None):
    default = {"Content-Type": "application/json"} if body else {}
    if headers:
        default.update(headers)
    return func.HttpRequest(
        method=method,
        body=json.dumps(body).encode() if body else b"",
        url=url,
        params={},
        headers=default,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealth:
    """Health endpoint has no auth — Traffic Manager probes must reach it."""

    def test_returns_200_without_auth(self):
        from function_app import health
        resp = health(_make_req())
        assert resp.status_code == 200

    def test_returns_site_name(self):
        from function_app import health
        data = json.loads(health(_make_req()).get_body())
        assert data["site"] == "Curtis Bay"

    def test_returns_healthy_status(self):
        from function_app import health
        data = json.loads(health(_make_req()).get_body())
        assert data["status"] == "healthy"


class TestMasterData:
    def _mock_conn(self, equipment_rows, reason_rows):
        conn = MagicMock()
        equip_cursor = MagicMock()
        equip_cursor.fetchall.return_value = equipment_rows
        reason_cursor = MagicMock()
        reason_cursor.fetchall.return_value = reason_rows
        conn.execute.side_effect = [equip_cursor, reason_cursor]
        return conn

    def test_returns_401_without_auth(self):
        from function_app import master_data
        resp = master_data(_make_req())
        assert resp.status_code == 401

    def test_returns_equipment_for_site(self):
        from function_app import master_data
        mock_conn = self._mock_conn(
            [("PUMP-01", "Feed Pump")],
            [("Mechanical Failure", "Unplanned")],
        )
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_make_req(headers=AUTH_HEADERS))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["equipment"] == [{"id": "PUMP-01", "name": "Feed Pump"}]

    def test_returns_shifts(self):
        from function_app import master_data
        mock_conn = self._mock_conn([], [])
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_make_req(headers=AUTH_HEADERS))
        data = json.loads(resp.get_body())
        assert data["shifts"] == ["Morning", "Afternoon", "Night"]

    def test_returns_500_on_db_error(self):
        from function_app import master_data
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=Exception("DB down"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_make_req(headers=AUTH_HEADERS))
        assert resp.status_code == 500


class TestRecords:
    def test_returns_401_without_auth(self):
        from function_app import records
        resp = records(_make_req())
        assert resp.status_code == 401

    def test_returns_200_with_empty_list(self):
        from function_app import records
        mock_conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.description = [
            ("id",), ("site_name",), ("equipment_id",), ("reason",),
            ("duration_minutes",), ("start_time",), ("operator_name",),
            ("category",), ("shift",),
        ]
        mock_conn.execute.return_value = cursor
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = records(_make_req(headers=AUTH_HEADERS))
        assert resp.status_code == 200
        assert json.loads(resp.get_body()) == []


class TestSubmit:
    def _mock_insert_conn(self, new_id=42):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = [new_id]
        conn.execute.return_value = cursor
        return conn

    def test_returns_403_without_auth(self):
        from function_app import submit
        resp = submit(_make_req("POST", {
            "equipment_id": "PUMP-01", "reason": "Failure",
            "duration_minutes": 30, "category": "Unplanned",
        }))
        assert resp.status_code == 403

    def test_returns_403_with_wrong_role(self):
        from function_app import submit
        headers = {
            "Content-Type":          "application/json",
            "X-MS-CLIENT-PRINCIPAL": _principal_header(["SiteManager"]),
        }
        resp = submit(_make_req("POST", {
            "equipment_id": "PUMP-01", "reason": "Failure",
            "duration_minutes": 30, "category": "Unplanned",
        }, headers=headers))
        assert resp.status_code == 403

    def test_returns_400_if_equipment_id_missing(self):
        from function_app import submit
        resp = submit(_make_req("POST", {
            "reason": "Mechanical Failure",
            "duration_minutes": 30,
            "category": "Unplanned",
        }, headers=OPERATOR_HEADERS))
        assert resp.status_code == 400

    def test_returns_400_if_category_missing(self):
        from function_app import submit
        resp = submit(_make_req("POST", {
            "equipment_id": "PUMP-01",
            "reason": "Mechanical Failure",
            "duration_minutes": 30,
        }, headers=OPERATOR_HEADERS))
        assert resp.status_code == 400

    def test_returns_400_on_invalid_json(self):
        from function_app import submit
        req = func.HttpRequest(
            method="POST",
            body=b"not json",
            url="http://localhost/api/submit",
            params={},
            headers={
                "Content-Type":          "application/json",
                "X-MS-CLIENT-PRINCIPAL": _principal_header(["Operator"]),
            },
        )
        resp = submit(req)
        assert resp.status_code == 400

    def test_saves_record_and_returns_id(self):
        from function_app import submit
        mock_conn = self._mock_insert_conn(new_id=7)
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = submit(_make_req("POST", {
                "equipment_id":     "PUMP-01",
                "reason":           "Mechanical Failure",
                "duration_minutes": 45,
                "category":         "Unplanned",
                "shift":            "Morning",
                "operator_name":    "Ali Hassan",
                "notes":            "",
            }, headers=OPERATOR_HEADERS))
        assert resp.status_code == 200
        data = json.loads(resp.get_body())
        assert data["id"] == 7
        assert data["site"] == "Curtis Bay"

    def test_stamps_site_name_from_env(self):
        from function_app import submit
        mock_conn = self._mock_insert_conn()
        with patch("function_app.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = submit(_make_req("POST", {
                "equipment_id": "PUMP-01", "reason": "Process Upset",
                "duration_minutes": 10, "category": "Unplanned",
            }, headers=OPERATOR_HEADERS))
        args = mock_conn.execute.call_args[0]
        assert args[1][0] == "Curtis Bay"
