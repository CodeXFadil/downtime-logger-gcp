import json
import os
from unittest.mock import patch, MagicMock

import flask
import pytest

os.environ.setdefault("DB_HOST",     "127.0.0.1")
os.environ.setdefault("DB_NAME",     "downtime-db")
os.environ.setdefault("DB_USER",     "testuser")
os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SITE_NAME",   "Curtis Bay")
os.environ.setdefault("REGION_KEY",  "us-central")

_app = flask.Flask(__name__)


def _req(method="GET", body=None, path="/"):
    with _app.test_request_context(
        path=path,
        method=method,
        data=json.dumps(body) if body else None,
        content_type="application/json",
    ):
        return flask.request._get_current_object()


class TestHealth:
    def test_returns_200(self):
        from main import health
        resp = health(_req())
        assert resp.status_code == 200

    def test_returns_site_name(self):
        from main import health
        data = json.loads(health(_req()).get_data())
        assert data["site"] == "Curtis Bay"

    def test_returns_healthy_status(self):
        from main import health
        data = json.loads(health(_req()).get_data())
        assert data["status"] == "healthy"


class TestMasterData:
    def _mock_conn(self, equipment_rows, reason_rows):
        conn = MagicMock()
        conn.run.side_effect = [equipment_rows, reason_rows]
        return conn

    def test_returns_equipment_for_site(self):
        from main import master_data
        mock_conn = self._mock_conn(
            [("PUMP-01", "Feed Pump")],
            [("Mechanical Failure", "Unplanned")],
        )
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_req())
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["equipment"] == [{"id": "PUMP-01", "name": "Feed Pump"}]

    def test_returns_shifts(self):
        from main import master_data
        mock_conn = self._mock_conn([], [])
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_req())
        data = json.loads(resp.get_data())
        assert data["shifts"] == ["Morning", "Afternoon", "Night"]

    def test_returns_500_on_db_error(self):
        from main import master_data
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=Exception("DB down"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = master_data(_req())
        assert resp.status_code == 500


class TestRecords:
    def test_returns_200_with_empty_list(self):
        from main import records
        mock_conn = MagicMock()
        mock_conn.run.return_value = []
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = records(_req())
        assert resp.status_code == 200
        assert json.loads(resp.get_data()) == []

    def test_returns_500_on_db_error(self):
        from main import records
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(side_effect=Exception("DB down"))
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = records(_req())
        assert resp.status_code == 500


class TestSubmit:
    def _mock_conn(self, new_id=42):
        conn = MagicMock()
        conn.run.return_value = [[new_id]]
        return conn

    def test_returns_400_if_equipment_id_missing(self):
        from main import submit
        resp = submit(_req("POST", {
            "reason": "Mechanical Failure",
            "duration_minutes": 30,
            "category": "Unplanned",
        }))
        assert resp.status_code == 400

    def test_returns_400_if_category_missing(self):
        from main import submit
        resp = submit(_req("POST", {
            "equipment_id": "PUMP-01",
            "reason": "Mechanical Failure",
            "duration_minutes": 30,
        }))
        assert resp.status_code == 400

    def test_returns_400_on_invalid_json(self):
        from main import submit
        with _app.test_request_context(
            path="/", method="POST",
            data=b"not json",
            content_type="application/json",
        ):
            resp = submit(flask.request._get_current_object())
        assert resp.status_code == 400

    def test_saves_record_and_returns_id(self):
        from main import submit
        mock_conn = self._mock_conn(new_id=7)
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resp = submit(_req("POST", {
                "equipment_id":     "PUMP-01",
                "reason":           "Mechanical Failure",
                "duration_minutes": 45,
                "category":         "Unplanned",
                "shift":            "Morning",
                "operator_name":    "Ali Hassan",
                "notes":            "",
            }))
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert data["id"] == 7
        assert data["site"] == "Curtis Bay"

    def test_stamps_site_name_from_env(self):
        from main import submit
        mock_conn = self._mock_conn()
        with patch("main.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = lambda s: mock_conn
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            submit(_req("POST", {
                "equipment_id": "PUMP-01", "reason": "Process Upset",
                "duration_minutes": 10, "category": "Unplanned",
            }))
        call_kwargs = mock_conn.run.call_args[1]
        assert call_kwargs["site"] == "Curtis Bay"
