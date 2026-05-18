"""
Storage-triggered Cloud Function.
Fires on every new file under records/ in Firebase Storage and streams the JSON
record into BigQuery for Power BI reporting.
"""
import json
import os

from google.cloud import bigquery
from google.cloud import storage as gcs

BQ_PROJECT = os.environ.get("GCP_PROJECT", "grace-np-dl-develop")
BQ_DATASET = os.environ.get("BQ_DATASET", "downtime_logger")
BQ_TABLE   = os.environ.get("BQ_TABLE",   "records")


def stream_to_bigquery(event, context):
    file_name   = event["name"]
    bucket_name = event["bucket"]

    # Ignore files outside records/
    if not file_name.startswith("records/"):
        print(f"Skipping {file_name} — not a record file")
        return

    # Read JSON from GCS
    blob = gcs.Client().bucket(bucket_name).blob(file_name)
    try:
        record = json.loads(blob.download_as_text())
    except Exception as exc:
        print(f"Failed to read {file_name}: {exc}")
        return

    # Derive region from path: records/{region}/{filename}
    parts = file_name.split("/")
    record.setdefault("region", parts[1] if len(parts) > 1 else "unknown")

    # Ensure duration_minutes is int (frontend sends it as int, but just in case)
    if "duration_minutes" in record:
        record["duration_minutes"] = int(record["duration_minutes"])

    # Stream insert into BigQuery
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    errors   = bigquery.Client().insert_rows_json(table_id, [record])
    if errors:
        print(f"BigQuery insert errors for {file_name}: {errors}")
    else:
        print(f"Streamed record {record.get('id')} ({record.get('site')}) → {table_id}")
