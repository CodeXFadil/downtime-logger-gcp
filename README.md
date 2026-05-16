# Plant Downtime Logger — GCP

Global downtime logging system for W.R. Grace manufacturing plants, built on Google Cloud Platform.

**GCP Project:** `grace-np-dl-develop`  
**Cost:** ~$15/month (all plants, 300 users)  
**Spec:** `docs/superpowers/specs/2026-05-16-gcp-downtime-logger-design.md`

---

## Stack

| Layer | Service |
|---|---|
| Frontend | Firebase Hosting (React SPA, global CDN) |
| Backend | Cloud Functions Gen 2 (Python 3.11) |
| Database | Cloud SQL PostgreSQL (`downtime-logger-db`, us-central1) |
| Auth | Firebase Authentication (email/password) |
| Secrets | Secret Manager |
| Analytics | Datastream → BigQuery (`Plant_Downtime`) → Power BI |

## Regions

| Region | GCP | Plant |
|---|---|---|
| us-central | us-central1 | Curtis Bay, Maryland |
| malaysia | asia-southeast1 | Kuantan, Malaysia |

---

## Project Structure

```
functions/          Cloud Functions Gen 2 (Python)
  main.py           All 4 endpoints: health, submit, records, master-data
  requirements.txt
  tests/
frontend/           React SPA (served via Firebase Hosting)
  index.html
scripts/            SQL scripts (PostgreSQL)
  migrate_schema.sql
  seed_master_data.sql
docs/
  business-case.md
  demo-script.md
  superpowers/specs/2026-05-16-gcp-downtime-logger-design.md
```

---

## Setup (one-time, run in order — confirm each step)

```bash
# 1. Enable Firebase Auth API
gcloud services enable identitytoolkit.googleapis.com --project grace-np-dl-develop

# 2. Create Cloud SQL instance
gcloud sql instances create downtime-logger-db \
  --database-version POSTGRES_15 \
  --tier db-f1-micro \
  --region us-central1 \
  --project grace-np-dl-develop

# 3. Create database and user
gcloud sql databases create downtime-db --instance downtime-logger-db --project grace-np-dl-develop
gcloud sql users create downtime_app --instance downtime-logger-db --project grace-np-dl-develop

# 4. Store DB password in Secret Manager
echo -n "YOUR_PASSWORD" | gcloud secrets create downtime-db-password \
  --data-file=- --project grace-np-dl-develop

# 5. Run schema + seed (via Cloud SQL Studio or psql proxy)
psql "host=... dbname=downtime-db user=downtime_app" -f scripts/migrate_schema.sql
psql "host=... dbname=downtime-db user=downtime_app" -f scripts/seed_master_data.sql

# 6. Create BigQuery dataset
bq mk --dataset --project grace-np-dl-develop Plant_Downtime
```

---

## Deploy

```bash
# Functions — us-central1 (Curtis Bay)
gcloud functions deploy downtime-logger-health-us \
  --gen2 --runtime python311 --region us-central1 \
  --source functions/ --entry-point health \
  --trigger-http --allow-unauthenticated \
  --set-env-vars SITE_NAME="Curtis Bay",REGION_KEY="us-central",DB_NAME="downtime-db",DB_USER="downtime_app",DB_HOST="<CLOUD_SQL_IP>" \
  --set-secrets DB_PASSWORD=downtime-db-password:latest \
  --project grace-np-dl-develop

# (repeat for submit, records, master-data — same flags, different --entry-point)

# Frontend
firebase deploy --only hosting --project grace-np-dl-develop
```

## Add a New Plant

1. `gcloud functions deploy downtime-logger-*-<region-suffix> ... --region <gcp-region> --set-env-vars SITE_NAME="<Plant Name>"`
2. Build frontend with `VITE_API_URL=<new-function-base-url>`
3. `firebase deploy --only hosting:<channel>`
