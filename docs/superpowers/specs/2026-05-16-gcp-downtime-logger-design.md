# Plant Downtime Logger — GCP Port Design
**Date:** 2026-05-16
**Author:** Muhammed Fadil
**Purpose:** Port the Azure-based Downtime Logger to GCP using the existing `grace-np-dl-develop` project

---

## Context

The Azure version of the Downtime Logger was designed for a COE pitch but the company does not have an Azure subscription at the level required to host the application. The company does have an established GCP project (`grace-np-dl-develop`) with the required services already enabled. This spec describes the GCP-native port of the same application.

**What stays the same:**
- React frontend (same SPA, same UX)
- PostgreSQL data schema (DowntimeRecords, Equipment, DowntimeReasons tables)
- Four HTTP endpoints (health, submit, records, master-data)
- Two-region POC (Curtis Bay + Kuantan)
- Power BI analytics layer
- ~$15/month total cost

**What changes:**
- Azure Functions → Cloud Functions Gen 2 (Python)
- Azure SQL → Cloud SQL (PostgreSQL)
- Azure Static Web Apps → Firebase Hosting
- Entra ID SSO → Firebase Authentication (email/password)
- Traffic Manager → site-aware frontend (regional Function URLs per plant)
- Key Vault → Secret Manager (already exists in project)
- Power BI direct SQL connection → Datastream CDC → BigQuery connector for Power BI
- Terraform → gcloud CLI + firebase CLI scripts

---

## GCP Project

| Field | Value |
|---|---|
| Project ID | `grace-np-dl-develop` |
| Project number | `478659741502` |
| Environment | Non-production (data lake) |
| Authenticated account | `muhammed.fadil@standardindustries.com` |

---

## Architecture

```
OPERATORS (browser / mobile browser)
         |
   Firebase Hosting (React SPA — global CDN, free)
         |
   site-aware API URL (env var set per regional deploy)
         |
   ┌─────────────────────┬──────────────────────────┐
   │                     │                          │
Cloud Functions Gen 2    Cloud Functions Gen 2     (future regions)
us-central1              asia-southeast1
Curtis Bay + others      Kuantan
   │                     │
   └─────────┬───────────┘
             │ pg8000 (pure Python PostgreSQL)
             │
   Cloud SQL — PostgreSQL (us-central1, central)
   downtime-db
   DowntimeRecords | Equipment | DowntimeReasons
             │
   Datastream (CDC, near real-time)
             │
   BigQuery — dataset: Plant_Downtime
   vw_downtime_global | vw_downtime_by_site | vw_downtime_by_equipment
             │
   Power BI (BigQuery connector)
   Cross-site dashboard | MTBF analysis

   Firebase Auth (email/password) ← operators log in
   Secret Manager ← SQL credentials (alongside augury_* secrets)
```

---

## Services

### Already enabled in `grace-np-dl-develop`

| Service | API |
|---|---|
| Cloud Functions Gen 2 | `cloudfunctions.googleapis.com` |
| Cloud Run (backing Gen 2) | `run.googleapis.com` |
| Cloud SQL | `sqladmin.googleapis.com` |
| BigQuery | `bigquery.googleapis.com` |
| Datastream | `datastream.googleapis.com` |
| Secret Manager | `secretmanager.googleapis.com` |
| Cloud Build | `cloudbuild.googleapis.com` |
| Artifact Registry | `artifactregistry.googleapis.com` |
| IAM | `iam.googleapis.com` |

### Needs enabling

| Service | API | Why |
|---|---|---|
| Firebase Authentication | `identitytoolkit.googleapis.com` | Operator login (email/password) |

---

## Regions

| Region key | GCP Region | Plant site |
|---|---|---|
| `us-central` | `us-central1` | Curtis Bay, Maryland (+ default for other US plants) |
| `malaysia` | `asia-southeast1` | Kuantan, Malaysia |

All existing Cloud Functions and Cloud Run services in the project use `us-central1`. We follow this convention.

---

## Multi-Region Routing (No Global LB)

Without Terraform, setting up a Global HTTP(S) Load Balancer manually is fragile (~15+ gcloud commands). Instead, routing is handled at the frontend layer:

- The React frontend reads `VITE_API_URL` at build time
- Each regional Firebase Hosting deployment is built with its region's Cloud Function base URL
- Curtis Bay operators hit the `us-central1` functions; Kuantan operators hit `asia-southeast1`
- Both function regions write to the **same central Cloud SQL** in `us-central1`
- Cross-site data is visible in BigQuery and Power BI in real time

**Adding a new plant:** deploy the same Cloud Functions to a new GCP region, build the frontend with that region's URL, deploy to Firebase Hosting as a new site or channel. One `gcloud functions deploy` + one `firebase deploy`.

---

## Backend — Cloud Functions Gen 2 (Python)

### Language and runtime

Python 3.11, `functions-framework` v3. The Azure Functions Python v2 code is nearly identical — swap `azure.functions` imports for `functions_framework` decorators, replace `pyodbc` (SQL Server ODBC) with `pg8000` (pure Python PostgreSQL, no system driver install needed on Cloud Functions).

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness — returns site name, region, DB host |
| POST | `/submit` | Insert downtime record |
| GET | `/records` | Return 50 most recent records across all sites |
| GET | `/master-data` | Return equipment list (site-specific), reasons (by category), shifts |

### Environment variables (per regional deploy)

| Variable | Example value |
|---|---|
| `SITE_NAME` | `Curtis Bay` |
| `REGION_KEY` | `us-central` |
| `DB_HOST` | Cloud SQL private IP or `/cloudsql/<connection-name>` |
| `DB_NAME` | `downtime-db` |
| `DB_USER` | `downtime_app` |
| `DB_PASSWORD` | Sourced from Secret Manager at deploy time |

### Naming convention (matches existing project pattern)

- `downtime-logger-health-us`
- `downtime-logger-submit-us`
- `downtime-logger-records-us`
- `downtime-logger-master-data-us`
- (same names with `-my` suffix for Malaysia)

---

## Database — Cloud SQL PostgreSQL

### Instance spec (POC)

| Field | Value |
|---|---|
| Instance ID | `downtime-logger-db` |
| Region | `us-central1` |
| Database version | `POSTGRES_15` |
| Machine type | `db-f1-micro` (~$10/month) |
| Storage | 10 GB SSD (auto-grow enabled) |
| Connectivity | Private IP via VPC (same VPC used by other project services) |

### Schema

Identical to the Azure version (PostgreSQL-compatible SQL — no SQL Server syntax):

```sql
CREATE TABLE DowntimeRecords (
    id               SERIAL PRIMARY KEY,
    site_name        VARCHAR(100) NOT NULL,
    equipment_id     VARCHAR(100) NOT NULL,
    reason           VARCHAR(200) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_time       TIMESTAMP DEFAULT NOW(),
    operator_name    VARCHAR(200),
    notes            TEXT,
    category         VARCHAR(20),   -- 'Planned' or 'Unplanned'
    shift            VARCHAR(20)    -- 'Morning', 'Afternoon', 'Night'
);

CREATE TABLE Equipment (
    id           SERIAL PRIMARY KEY,
    site_name    VARCHAR(100) NOT NULL,
    equipment_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (site_name, equipment_id)
);

CREATE TABLE DowntimeReasons (
    reason_id   SERIAL PRIMARY KEY,
    reason_name VARCHAR(200) NOT NULL UNIQUE,
    category    VARCHAR(20) NOT NULL,  -- 'Planned' or 'Unplanned'
    active      BOOLEAN NOT NULL DEFAULT TRUE
);
```

### BigQuery views (in `Plant_Downtime` dataset)

| View | Purpose |
|---|---|
| `vw_downtime_global` | Cross-site comparison — COE global view |
| `vw_downtime_by_site` | Daily downtime summary per site |
| `vw_downtime_by_equipment` | MTBF analysis per equipment type |
| `vw_planned_vs_unplanned` | OEE input — Planned/Unplanned split per site |

---

## Analytics — Datastream + BigQuery + Power BI

### Datastream (Cloud SQL → BigQuery)

Datastream performs Change Data Capture (CDC) on the Cloud SQL PostgreSQL instance and replicates changes to BigQuery in near real-time. This is cleaner than the Azure version (which used a direct Power BI → SQL Server connection).

- Source: Cloud SQL PostgreSQL (`downtime-db`)
- Destination: BigQuery dataset `Plant_Downtime`
- Tables to replicate: `DowntimeRecords`, `Equipment`, `DowntimeReasons`
- Latency: < 1 minute from write to BigQuery availability

### Power BI

Power BI connects to BigQuery via the native BigQuery connector (no gateway required). Views in `Plant_Downtime` are the only objects exposed — raw replicated tables are not used directly in reports.

---

## Authentication — Firebase Authentication

- Provider: Email/Password
- One account per operator, provisioned by the site coordinator
- Firebase Auth SDK loaded in the React frontend
- On login, Firebase issues a JWT — the frontend attaches it as `Authorization: Bearer <token>` on all API calls
- Cloud Functions verify the JWT using the Firebase Admin SDK

**No IT dependency** — provisioning is self-service via the Firebase Console or a simple admin script. No Active Directory integration required for the POC.

---

## Secrets — Secret Manager

Two new secrets added alongside the existing `augury_username` / `augury_password`:

| Secret name | Content |
|---|---|
| `downtime-db-password` | Cloud SQL `downtime_app` user password |
| `downtime-firebase-config` | Firebase project config JSON (for functions) |

---

## Deployment — gcloud CLI + firebase CLI

No Terraform. Infrastructure is set up via documented gcloud commands (one-time) and deployed via `gcloud functions deploy` + `firebase deploy`.

### One-time setup sequence (ask before executing each step)

1. Enable Firebase Authentication API
2. Create Cloud SQL instance `downtime-logger-db`
3. Create database `downtime-db` and user `downtime_app`
4. Run schema migration SQL
5. Seed Equipment and DowntimeReasons master data
6. Store DB password in Secret Manager
7. Create Firebase project linked to `grace-np-dl-develop`
8. Create BigQuery dataset `Plant_Downtime`
9. Configure Datastream stream (Cloud SQL → BigQuery)

### Per-deploy (ongoing)

```bash
# Deploy functions — us-central1
gcloud functions deploy downtime-logger-submit-us \
  --gen2 --runtime python311 --region us-central1 \
  --source functions/ --entry-point submit \
  --trigger-http --allow-unauthenticated \
  --set-env-vars SITE_NAME="Curtis Bay",REGION_KEY="us-central" \
  --set-secrets DB_PASSWORD=downtime-db-password:latest \
  --project grace-np-dl-develop

# Deploy frontend
firebase deploy --only hosting --project grace-np-dl-develop
```

---

## Cost

| Service | Monthly cost |
|---|---|
| Cloud Functions Gen 2 (2 regions) | ~$0 (free tier) |
| Cloud SQL db-f1-micro | ~$10 |
| Firebase Hosting | $0 |
| Firebase Auth (≤ 50K users/month) | $0 |
| BigQuery Plant_Downtime dataset | ~$0 |
| Datastream (low volume) | ~$5 |
| Secret Manager | ~$0 |
| **Total — all plants, 300 users** | **~$15/month** |

---

## What Is Not in Scope

- Global HTTP(S) Load Balancer (replaced by site-aware frontend)
- Terraform (replaced by gcloud + firebase CLI)
- Active Directory / SAML federation (deferred to post-COE-approval IT engagement)
- Progressive Web App / offline support (Phase 2)
- Cloud Armor (WAF) — acceptable for POC; add post-approval
- Production Cloud SQL tier upgrade (db-f1-micro is POC only)
- CI/CD pipeline (deferred to post-COE-approval)
