"""
Local demo server — serves the frontend and proxies API calls to Cloud Functions
using your active gcloud credentials. No IAM changes required.

Usage:
    python demo_server.py
    Open http://localhost:8080
"""
import os
import subprocess
import sys

import requests
from flask import Flask, Response, request, send_from_directory

GCLOUD = (
    r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    if sys.platform == "win32" else "gcloud"
)

_BASE = "https://{}-rplpwbvuwq-uc.a.run.app"
ROUTES = {
    "/api/health":      _BASE.format("health"),
    "/api/master-data": _BASE.format("master-data"),
    "/api/records":     _BASE.format("records"),
    "/api/submit":      _BASE.format("submit"),
}

FRONTEND = os.path.join(os.path.dirname(__file__), "frontend")
app = Flask(__name__, static_folder=FRONTEND)


def _token():
    result = subprocess.run(
        [GCLOUD, "auth", "print-identity-token"],
        capture_output=True, text=True,
        shell=(sys.platform == "win32"),
    )
    return result.stdout.strip()


@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.route("/api/<path:path>", methods=["GET", "POST"])
def proxy(path):
    target = ROUTES.get(f"/api/{path}")
    if not target:
        return Response('{"error":"unknown route"}', status=404, mimetype="application/json")

    # Cloud Run IAM requires a gcloud OIDC token in Authorization
    # Pass the browser's Firebase token in a custom header so Python code can verify it
    firebase_auth = request.headers.get("Authorization", "")
    headers = {
        "Authorization":    f"Bearer {_token()}",
        "Content-Type":     "application/json",
        "X-Firebase-Token": firebase_auth.removeprefix("Bearer ").strip(),
    }
    if request.method == "POST":
        resp = requests.post(target, data=request.get_data(), headers=headers, timeout=20)
    else:
        resp = requests.get(target, headers=headers, timeout=20)

    return Response(resp.content, status=resp.status_code, mimetype="application/json")


if __name__ == "__main__":
    print("\n  Plant Downtime Logger - GCP Demo")
    print("  ----------------------------------")
    print("  Open in browser: http://localhost:8080\n")
    app.run(host="0.0.0.0", port=8080, debug=False)
