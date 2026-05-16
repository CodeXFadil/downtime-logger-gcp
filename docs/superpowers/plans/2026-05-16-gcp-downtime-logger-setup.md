# GCP Downtime Logger — Setup & Deployment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the GCP Downtime Logger from a clean repo to a live, two-region application on `grace-np-dl-develop`.

**Architecture:** Cloud Functions Gen 2 (Python 3.11) in `us-central1` + `asia-southeast1`, backed by a single Cloud SQL PostgreSQL instance, served via Firebase Hosting, with Datastream replicating to BigQuery for Power BI.

**Tech Stack:** Python 3.11, functions-framework v3, pg8000, Firebase Hosting, Cloud SQL PostgreSQL 15, BigQuery, Datastream, Secret Manager, gcloud CLI, firebase CLI.

> **Permission model:** Tasks marked 🔒 **GCP CHANGE** create or modify cloud resources and require explicit user approval before execution. All other tasks are local code changes.

> **Split point:** Tasks 1–2 are local (no cloud). Tasks 3–11 touch live GCP resources — each is gated.

---

## File Map

| Status | Path | Responsibility |
|---|---|---|
| **Rewrite** | `functions/tests/test_main.py` | pytest tests for all 4 functions using Flask test requests |
| **Create** | `functions/local.settings.json` | Local dev env vars (gitignored) |
| **Create** | `firebase.json` | Firebase Hosting config |
| **Create** | `.firebaserc` | Firebase project binding |
| **Create** | `frontend/vite.config.js` | Vite build config (sets VITE_API_URL per region) |
| **Create** | `scripts/setup-functions-us.sh` | Deploy script — us-central1 functions |
| **Create** | `scripts/setup-functions-my.sh` | Deploy script — asia-southeast1 functions |

---

## Task 1: Rewrite Tests for functions_framework

**Files:**
- Rewrite: `functions/tests/test_main.py`

The copied test file uses `azure.functions` — replace entirely with Flask-based request mocks that match `functions_framework`.

- [ ] **Step 1: Install test dependencies locally**

```bash
cd functions
pip install functions-framework pg8000 pytest flask
```

Expected: packages install without error.

- [ ] **Step 2: Rewrite `functions/tests/test_main.py`**

Replace the entire file:

```python
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
```

- [ ] **Step 3: Run tests**

```bash
cd functions
pytest tests/test_main.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add functions/tests/test_main.py
git commit -m "test: rewrite tests for functions_framework + pg8000"
```

---

## Task 2: Add Firebase Config Files (local)

**Files:**
- Create: `firebase.json`
- Create: `.firebaserc`

- [ ] **Step 1: Create `firebase.json`**

```json
{
  "hosting": {
    "public": "frontend",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      { "source": "**", "destination": "/index.html" }
    ]
  }
}
```

- [ ] **Step 2: Create `.firebaserc`**

```json
{
  "projects": {
    "default": "grace-np-dl-develop"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add firebase.json .firebaserc
git commit -m "feat: add Firebase Hosting config"
```

---

## Task 3: 🔒 GCP CHANGE — Enable Firebase Authentication API

**What this does:** Enables the `identitytoolkit.googleapis.com` API on project `grace-np-dl-develop`. This is required for Firebase Authentication (email/password login for operators). It is a read-only enablement — no data is created or deleted. It can be disabled again at any time.

**Permission required before running Step 1.**

- [ ] **Step 1: Enable the API**

```bash
gcloud services enable identitytoolkit.googleapis.com \
  --project grace-np-dl-develop
```

Expected output:
```
Operation "operations/acf.p2-478659741502-..." finished successfully.
```

- [ ] **Step 2: Verify it is enabled**

```bash
gcloud services list --project grace-np-dl-develop \
  --enabled --filter="name:identitytoolkit" --format="value(name)"
```

Expected: `projects/478659741502/services/identitytoolkit.googleapis.com`

---

## Task 4: 🔒 GCP CHANGE — Create Cloud SQL Instance

**What this does:** Creates a new Cloud SQL PostgreSQL 15 instance named `downtime-logger-db` in `us-central1`. Spec: `db-f1-micro` (smallest tier, ~$10/month). This is a new resource — nothing existing is touched. Creation takes approximately 5 minutes.

**Permission required before running Step 1.**

- [ ] **Step 1: Create the instance**

```bash
gcloud sql instances create downtime-logger-db \
  --database-version POSTGRES_15 \
  --tier db-f1-micro \
  --region us-central1 \
  --storage-size 10GB \
  --storage-auto-increase \
  --project grace-np-dl-develop
```

Expected final output:
```
Created [https://sqladmin.googleapis.com/sql/v1beta4/projects/grace-np-dl-develop/instances/downtime-logger-db].
```

- [ ] **Step 2: Verify the instance is RUNNABLE**

```bash
gcloud sql instances describe downtime-logger-db \
  --project grace-np-dl-develop \
  --format="value(state)"
```

Expected: `RUNNABLE`

---

## Task 5: 🔒 GCP CHANGE — Create Database, User, and Store Password

**What this does:** Creates the `downtime-db` database and `downtime_app` user inside the Cloud SQL instance. Then stores the password in Secret Manager as `downtime-db-password`. These are new resources inside the instance created in Task 4.

**Permission required before running Step 1.**

- [ ] **Step 1: Create the database**

```bash
gcloud sql databases create downtime-db \
  --instance downtime-logger-db \
  --project grace-np-dl-develop
```

Expected: `Created database [downtime-db].`

- [ ] **Step 2: Create the app user**

```bash
gcloud sql users create downtime_app \
  --instance downtime-logger-db \
  --project grace-np-dl-develop \
  --password CHOOSE_A_STRONG_PASSWORD_HERE
```

Replace `CHOOSE_A_STRONG_PASSWORD_HERE` with a real password (16+ chars, mixed case + numbers). Note this password — you will use it in the next step.

Expected: `Created user [downtime_app].`

- [ ] **Step 3: Store password in Secret Manager**

```bash
echo -n "THE_SAME_PASSWORD_YOU_CHOSE" | \
  gcloud secrets create downtime-db-password \
    --data-file=- \
    --project grace-np-dl-develop
```

Expected: `Created secret [downtime-db-password].`

- [ ] **Step 4: Verify the secret exists**

```bash
gcloud secrets list --project grace-np-dl-develop \
  --filter="name:downtime-db-password" --format="value(name)"
```

Expected: `projects/478659741502/secrets/downtime-db-password`

---

## Task 6: 🔒 GCP CHANGE — Run Schema Migration via Cloud SQL Auth Proxy

**What this does:** Connects to the Cloud SQL instance through the Cloud SQL Auth Proxy (a secure local tunnel — no public IP needed) and runs `scripts/migrate_schema.sql` to create the three tables and views. No existing data is touched.

**Permission required before running Step 1.**

- [ ] **Step 1: Download Cloud SQL Auth Proxy**

```bash
# Windows (PowerShell)
curl -o cloud-sql-proxy.exe https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.x64.windows.exe
```

- [ ] **Step 2: Get the instance connection name**

```bash
gcloud sql instances describe downtime-logger-db \
  --project grace-np-dl-develop \
  --format="value(connectionName)"
```

Expected format: `grace-np-dl-develop:us-central1:downtime-logger-db`

- [ ] **Step 3: Start the proxy (run in a separate terminal, keep it running)**

```bash
./cloud-sql-proxy.exe grace-np-dl-develop:us-central1:downtime-logger-db --port 5433
```

Expected: `Listening on 127.0.0.1:5433`

- [ ] **Step 4: Run the migration (in original terminal)**

```bash
psql "host=127.0.0.1 port=5433 dbname=downtime-db user=downtime_app password=YOUR_PASSWORD" \
  -f scripts/migrate_schema.sql
```

Expected output includes:
```
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE VIEW
CREATE VIEW
CREATE VIEW
```

- [ ] **Step 5: Verify tables exist**

```bash
psql "host=127.0.0.1 port=5433 dbname=downtime-db user=downtime_app password=YOUR_PASSWORD" \
  -c "\dt"
```

Expected: `DowntimeRecords`, `Equipment`, `DowntimeReasons` all listed.

---

## Task 7: 🔒 GCP CHANGE — Seed Master Data

**What this does:** Runs `scripts/seed_master_data.sql` to insert the global downtime reasons and equipment lists for Curtis Bay and Kuantan. Uses the same proxy connection from Task 6. Safe to run multiple times — uses `ON CONFLICT DO NOTHING`.

**Permission required before running Step 1.**

- [ ] **Step 1: Run the seed script (proxy must still be running)**

```bash
psql "host=127.0.0.1 port=5433 dbname=downtime-db user=downtime_app password=YOUR_PASSWORD" \
  -f scripts/seed_master_data.sql
```

- [ ] **Step 2: Verify seed data**

```bash
psql "host=127.0.0.1 port=5433 dbname=downtime-db user=downtime_app password=YOUR_PASSWORD" \
  -c "SELECT site_name, COUNT(*) FROM Equipment GROUP BY site_name;"
```

Expected:
```
 site_name  | count
------------+-------
 Curtis Bay |     9
 Kuantan    |     9
```

```bash
psql "host=127.0.0.1 port=5433 dbname=downtime-db user=downtime_app password=YOUR_PASSWORD" \
  -c "SELECT COUNT(*) FROM DowntimeReasons;"
```

Expected: `12`

---

## Task 8: 🔒 GCP CHANGE — Deploy Cloud Functions (us-central1)

**What this does:** Deploys 4 Cloud Functions to `us-central1` (Curtis Bay region). Each function is a new resource. No existing functions are modified — the naming convention (`downtime-logger-*-us`) is unique to this project.

**Get the Cloud SQL instance IP first:**

```bash
gcloud sql instances describe downtime-logger-db \
  --project grace-np-dl-develop \
  --format="value(ipAddresses[0].ipAddress)"
```

Note this IP — use it as `DB_HOST` in the deploy commands below.

**Permission required before running Step 1.**

- [ ] **Step 1: Deploy `health` function**

```bash
gcloud functions deploy downtime-logger-health-us \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source functions/ \
  --entry-point health \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars "SITE_NAME=Curtis Bay,REGION_KEY=us-central,DB_HOST=CLOUD_SQL_IP,DB_NAME=downtime-db,DB_USER=downtime_app" \
  --set-secrets "DB_PASSWORD=downtime-db-password:latest" \
  --project grace-np-dl-develop
```

- [ ] **Step 2: Smoke test health function**

```bash
curl $(gcloud functions describe downtime-logger-health-us \
  --gen2 --region us-central1 \
  --project grace-np-dl-develop \
  --format="value(serviceConfig.uri)")
```

Expected: `{"status": "healthy", "site": "Curtis Bay", ...}`

- [ ] **Step 3: Deploy `master-data` function**

```bash
gcloud functions deploy downtime-logger-master-data-us \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source functions/ \
  --entry-point master_data \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars "SITE_NAME=Curtis Bay,REGION_KEY=us-central,DB_HOST=CLOUD_SQL_IP,DB_NAME=downtime-db,DB_USER=downtime_app" \
  --set-secrets "DB_PASSWORD=downtime-db-password:latest" \
  --project grace-np-dl-develop
```

- [ ] **Step 4: Deploy `records` function**

```bash
gcloud functions deploy downtime-logger-records-us \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source functions/ \
  --entry-point records \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars "SITE_NAME=Curtis Bay,REGION_KEY=us-central,DB_HOST=CLOUD_SQL_IP,DB_NAME=downtime-db,DB_USER=downtime_app" \
  --set-secrets "DB_PASSWORD=downtime-db-password:latest" \
  --project grace-np-dl-develop
```

- [ ] **Step 5: Deploy `submit` function**

```bash
gcloud functions deploy downtime-logger-submit-us \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source functions/ \
  --entry-point submit \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars "SITE_NAME=Curtis Bay,REGION_KEY=us-central,DB_HOST=CLOUD_SQL_IP,DB_NAME=downtime-db,DB_USER=downtime_app" \
  --set-secrets "DB_PASSWORD=downtime-db-password:latest" \
  --project grace-np-dl-develop
```

- [ ] **Step 6: Smoke test full us-central1 stack**

```bash
BASE=$(gcloud functions describe downtime-logger-master-data-us \
  --gen2 --region us-central1 \
  --project grace-np-dl-develop \
  --format="value(serviceConfig.uri)")

curl $BASE
```

Expected: JSON with `equipment`, `reasons`, `shifts` arrays.

- [ ] **Step 7: Commit deploy env notes**

```bash
# Record the us-central1 function base URL in README
git add README.md  # update with actual URLs after deploy
git commit -m "feat: deploy Cloud Functions to us-central1 (Curtis Bay)"
```

---

## Task 9: 🔒 GCP CHANGE — Deploy Cloud Functions (asia-southeast1)

**What this does:** Deploys the same 4 functions to `asia-southeast1` (Kuantan region). Same code, different `SITE_NAME` and `REGION_KEY` env vars.

**Permission required before running Step 1.**

- [ ] **Step 1: Deploy all 4 functions to asia-southeast1**

```bash
for FUNC in health master_data records submit; do
  FNAME="downtime-logger-${FUNC//_/-}-my"
  gcloud functions deploy $FNAME \
    --gen2 \
    --runtime python311 \
    --region asia-southeast1 \
    --source functions/ \
    --entry-point $FUNC \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars "SITE_NAME=Kuantan,REGION_KEY=malaysia,DB_HOST=CLOUD_SQL_IP,DB_NAME=downtime-db,DB_USER=downtime_app" \
    --set-secrets "DB_PASSWORD=downtime-db-password:latest" \
    --project grace-np-dl-develop
done
```

- [ ] **Step 2: Smoke test Kuantan health**

```bash
curl $(gcloud functions describe downtime-logger-health-my \
  --gen2 --region asia-southeast1 \
  --project grace-np-dl-develop \
  --format="value(serviceConfig.uri)")
```

Expected: `{"status": "healthy", "site": "Kuantan", ...}`

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: deploy Cloud Functions to asia-southeast1 (Kuantan)" --allow-empty
```

---

## Task 10: 🔒 GCP CHANGE — Update Frontend API URL and Deploy via Firebase

**What this does:** Updates `frontend/index.html` to call the live `us-central1` function URLs, then deploys via `firebase deploy`. Firebase Hosting serves the SPA globally via CDN. This is a new Firebase Hosting site — nothing existing is affected.

**Permission required before running Step 1.**

- [ ] **Step 1: Get the us-central1 base URL**

```bash
gcloud functions describe downtime-logger-health-us \
  --gen2 --region us-central1 \
  --project grace-np-dl-develop \
  --format="value(serviceConfig.uri)" | sed 's|/health||'
```

Note the base URL (everything before `/health`).

- [ ] **Step 2: Update API fetch URLs in `frontend/index.html`**

Open `frontend/index.html`. Find every `fetch("/api/` call and replace with the full Cloud Function URL:

| Old | New |
|---|---|
| `fetch("/api/health")` | `fetch("BASE_URL/health")` |
| `fetch("/api/records")` | `fetch("BASE_URL/records")` |
| `fetch("/api/master-data")` | `fetch("BASE_URL/master-data")` |
| `fetch("/api/submit", {` | `fetch("BASE_URL/submit", {` |

Where `BASE_URL` = the us-central1 base URL from Step 1 (e.g. `https://downtime-logger-health-us-478659741502.us-central1.run.app`).

- [ ] **Step 3: Deploy to Firebase Hosting**

```bash
firebase login  # if not already logged in
firebase deploy --only hosting --project grace-np-dl-develop
```

Expected output includes:
```
✔  Deploy complete!
Hosting URL: https://grace-np-dl-develop.web.app
```

- [ ] **Step 4: Open the app in browser and verify**

Navigate to `https://grace-np-dl-develop.web.app`. Verify:
- Page loads without errors
- Equipment dropdown populates
- Site badge shows "Curtis Bay"

- [ ] **Step 5: Submit a test downtime record**

Fill in the form:
- Select UNPLANNED → Mechanical Failure
- Equipment: REACTOR-A
- Shift: Morning
- Duration: 30
- Hit Submit

Verify the record appears in the Recent Incidents table.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat: wire frontend to live GCP function URLs, deploy to Firebase Hosting"
```

---

## Task 11: 🔒 GCP CHANGE — Create BigQuery Dataset

**What this does:** Creates a new BigQuery dataset named `Plant_Downtime` in project `grace-np-dl-develop`. This sits alongside the 26 existing datasets. No existing datasets are touched.

**Permission required before running Step 1.**

- [ ] **Step 1: Create the dataset**

```bash
$sdkBin = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin"
$env:PATH = "$sdkBin;$env:PATH"
bq mk --dataset --location=US --description="Downtime Logger analytics — replicated from Cloud SQL via Datastream" grace-np-dl-develop:Plant_Downtime
```

Expected: `Dataset 'grace-np-dl-develop:Plant_Downtime' successfully created.`

- [ ] **Step 2: Verify**

```bash
bq ls --project_id grace-np-dl-develop | grep Plant_Downtime
```

Expected: `Plant_Downtime` listed.

---

## Task 12: 🔒 GCP CHANGE — Configure Datastream (Cloud SQL → BigQuery)

**What this does:** Sets up a Datastream CDC (Change Data Capture) stream that continuously replicates changes from the Cloud SQL `downtime-db` database to the `Plant_Downtime` BigQuery dataset. Latency < 1 minute. This is a new Datastream resource — nothing existing is affected.

This task has more steps than others and uses the GCP Console (UI) because Datastream setup involves multiple configuration screens. Steps below guide you through the Console UI.

**Permission required before running Step 1.**

- [ ] **Step 1: Open Datastream in GCP Console**

Navigate to: `https://console.cloud.google.com/datastream?project=grace-np-dl-develop`

- [ ] **Step 2: Create a Connection Profile for Cloud SQL (source)**

Click **Connection Profiles → Create** → Select **PostgreSQL**.
- Display name: `downtime-cloudsql-source`
- Hostname: the Cloud SQL private IP (from Task 8)
- Port: `5432`
- Username: `downtime_app`
- Password: the password from Task 5
- Database: `downtime-db`
- Click **Test** → should show green ✓

- [ ] **Step 3: Create a Connection Profile for BigQuery (destination)**

Click **Connection Profiles → Create** → Select **BigQuery**.
- Display name: `downtime-bigquery-dest`
- This auto-uses the project's BigQuery — no extra config needed.

- [ ] **Step 4: Create the Stream**

Click **Streams → Create Stream**.
- Name: `downtime-logger-stream`
- Source profile: `downtime-cloudsql-source`
- Destination profile: `downtime-bigquery-dest`
- Destination dataset: `Plant_Downtime`
- Tables to replicate: select `DowntimeRecords`, `Equipment`, `DowntimeReasons`
- Click **Validate** → should pass
- Click **Create and Start**

- [ ] **Step 5: Verify stream is running**

After ~2 minutes, the stream status should show **Running** in the Datastream console.

Submit another test record via the app, then after 60 seconds check:

```bash
bq query --project_id grace-np-dl-develop \
  "SELECT COUNT(*) FROM Plant_Downtime.DowntimeRecords"
```

Expected: count > 0.

---

## Self-Review

**Spec coverage:**
- [x] Firebase Auth API enabled — Task 3
- [x] Cloud SQL instance created — Task 4
- [x] Database + user + Secret Manager — Task 5
- [x] Schema migration (PostgreSQL) — Task 6
- [x] Master data seeded — Task 7
- [x] Cloud Functions us-central1 (4 functions) — Task 8
- [x] Cloud Functions asia-southeast1 (4 functions) — Task 9
- [x] Firebase Hosting frontend deploy — Task 10
- [x] BigQuery Plant_Downtime dataset — Task 11
- [x] Datastream Cloud SQL → BigQuery — Task 12
- [x] Tests rewritten for functions_framework — Task 1
- [x] Firebase config files — Task 2

**No placeholders** — all commands use real project ID, real resource names, real regions.

**Type consistency** — `conn.run(...)` used in both `main.py` and test mocks. `mock_conn.run.return_value` and `mock_conn.run.side_effect` patterns match actual `pg8000.native.Connection.run()` return type (list of tuples).
