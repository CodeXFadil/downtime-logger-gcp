import json
import os
from unittest.mock import patch, MagicMock

import flask
import pytest

os.environ.setdefault("GCS_BUCKET",  "test-bucket")
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


def _mock_bucket():
    """Return a MagicMock that stands in for storage.Client().bucket(...)."""
    bucket = MagicMock()
    client = MagicMock()
    client.return_value.bucket.return_value = bucket
    return client, bucket


class TestHealth:
    def test_returns_200(self):
        from main import health
        assert health(_req()).status_code == 200

    def test_returns_site_name(self):
        from main import health
        assert json.loads(health(_req()).get_data())["site"] == "Curtis Bay"

    def test_returns_healthy_status(self):
        from main import health
        assert json.loads(health(_req()).get_data())["status"] == "healthy"


class TestMasterData:
    def _setup_blobs(self, bucket, equipment, reasons):
        blob = MagicMock()
        blob.download_as_text.side_effect = [
            json.dumps(equipment),
            json.dumps(reasons),
        ]
        bucket.blob.return_value = blob

    def test_returns_equipment_for_site(self):
        from main import master_data
        client, bucket = _mock_bucket()
        self._setup_blobs(bucket,
            [{"id": "PUMP-01", "name": "Feed Pump", "site": "Curtis Bay"},
             {"id": "PUMP-01", "name": "Feed Pump", "site": "Kuantan"}],
            [],
        )
        with patch("main.storage.Client", client):
            data = json.loads(master_data(_req()).get_data())
        assert data["equipment"] == [{"id": "PUMP-01", "name": "Feed Pump"}]

    def test_filters_equipment_by_site(self):
        from main import master_data
        client, bucket = _mock_bucket()
        self._setup_blobs(bucket,
            [{"id": "PUMP-01", "name": "Feed Pump", "site": "Curtis Bay"},
             {"id": "PUMP-02", "name": "Other Pump", "site": "Kuantan"}],
            [],
        )
        with patch("main.storage.Client", client):
            data = json.loads(master_data(_req()).get_data())
        assert len(data["equipment"]) == 1
        assert data["equipment"][0]["id"] == "PUMP-01"

    def test_returns_shifts(self):
        from main import master_data
        client, bucket = _mock_bucket()
        self._setup_blobs(bucket, [], [])
        with patch("main.storage.Client", client):
            data = json.loads(master_data(_req()).get_data())
        assert data["shifts"] == ["Morning", "Afternoon", "Night"]

    def test_returns_500_on_gcs_error(self):
        from main import master_data
        client = MagicMock()
        client.return_value.bucket.side_effect = Exception("GCS down")
        with patch("main.storage.Client", client):
            resp = master_data(_req())
        assert resp.status_code == 500


class TestRecords:
    def test_returns_200_with_empty_list(self):
        from main import records
        client, bucket = _mock_bucket()
        bucket.list_blobs.return_value = []
        with patch("main.storage.Client", client):
            resp = records(_req())
        assert resp.status_code == 200
        assert json.loads(resp.get_data()) == []

    def test_returns_records_from_bucket(self):
        from main import records
        client, bucket = _mock_bucket()
        blob = MagicMock()
        blob.name = "records/us-central/2026-05-16T10-00-00-abc.json"
        blob.download_as_text.return_value = json.dumps({"id": "abc", "site": "Curtis Bay"})
        bucket.list_blobs.return_value = [blob]
        with patch("main.storage.Client", client):
            data = json.loads(records(_req()).get_data())
        assert data == [{"id": "abc", "site": "Curtis Bay"}]

    def test_returns_500_on_gcs_error(self):
        from main import records
        client = MagicMock()
        client.return_value.bucket.side_effect = Exception("GCS down")
        with patch("main.storage.Client", client):
            resp = records(_req())
        assert resp.status_code == 500


class TestSubmit:
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
        client, bucket = _mock_bucket()
        bucket.blob.return_value.upload_from_string = MagicMock()
        with patch("main.storage.Client", client):
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
        assert "id" in data
        assert data["site"] == "Curtis Bay"

    def test_stamps_site_name(self):
        from main import submit
        client, bucket = _mock_bucket()
        uploaded = {}

        def capture_upload(content, content_type=None):
            uploaded["record"] = json.loads(content)

        bucket.blob.return_value.upload_from_string = capture_upload
        with patch("main.storage.Client", client):
            submit(_req("POST", {
                "equipment_id": "PUMP-01",
                "reason": "Process Upset",
                "duration_minutes": 10,
                "category": "Unplanned",
            }))
        assert uploaded["record"]["site"] == "Curtis Bay"
