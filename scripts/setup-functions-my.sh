#!/usr/bin/env bash
# Deploy Cloud Functions Gen 2 to asia-southeast1 (Kuantan)
# Usage: DB_HOST=<cloud-sql-ip> bash scripts/setup-functions-my.sh
set -euo pipefail

PROJECT="grace-np-dl-develop"
REGION="asia-southeast1"
SITE_NAME="Kuantan"
REGION_KEY="malaysia"
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

gcloud functions deploy downtime-logger-health-my      --entry-point health      "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-master-data-my --entry-point master_data "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-records-my     --entry-point records     "${BASE_FLAGS[@]}"
gcloud functions deploy downtime-logger-submit-my      --entry-point submit      "${BASE_FLAGS[@]}"

echo ""
echo "asia-southeast1 functions deployed. Smoke test:"
BASE=$(gcloud functions describe downtime-logger-health-my \
  --gen2 --region "$REGION" --project "$PROJECT" \
  --format="value(serviceConfig.uri)")
echo "Health: $BASE"
curl -s "$BASE" | python3 -m json.tool
