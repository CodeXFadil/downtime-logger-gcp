#!/usr/bin/env bash
# Deploy Cloud Functions Gen 2 to us-central1 (Curtis Bay)
# Usage: DB_HOST=<cloud-sql-ip> bash scripts/setup-functions-us.sh
set -euo pipefail

PROJECT="grace-np-dl-develop"
REGION="us-central1"
SITE_NAME="Curtis Bay"
REGION_KEY="us-central"
DB_HOST="${DB_HOST:?Set DB_HOST to the Cloud SQL private IP}"
DB_NAME="downtime-db"
DB_USER="downtime_app"

BASE_FLAGS=(
  --gen2
  --runtime python311
  --region "$REGION"
  --source functions/
  --trigger-http
  --allow-unauthenticated
  --set-env-vars "SITE_NAME=${SITE_NAME},REGION_KEY=${REGION_KEY},DB_HOST=${DB_HOST},DB_NAME=${DB_NAME},DB_USER=${DB_USER}"
  --set-secrets "DB_PASSWORD=downtime-db-password:latest"
  --project "$PROJECT"
)

gcloud functions deploy downtime-logger-health-us     --entry-point health      "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-master-data-us --entry-point master_data "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-records-us    --entry-point records     "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-submit-us     --entry-point submit      "${BASE_FLAGS[@]}"

echo ""
echo "us-central1 functions deployed. Smoke test:"
BASE=$(gcloud functions describe downtime-logger-health-us \
  --gen2 --region "$REGION" --project "$PROJECT" \
  --format="value(serviceConfig.uri)")
echo "Health: $BASE"
curl -s "$BASE" | python3 -m json.tool
