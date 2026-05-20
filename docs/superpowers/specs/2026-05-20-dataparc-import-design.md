# DataParc Batch Import — Design Spec

**Date:** 2026-05-20
**Author:** Muhammed Fadil
**Project:** Grace Downtime Logger (GCP — `grace-np-dl-develop`)

---

## Problem

Operators receive Excel exports from DataParc (process historian) containing 5–10 downtime events per file. Each export has start time and end time only — no equipment, category, or reason. The current workflow is to manually fill in the missing fields in Excel and upload to a separate uptime reporting system. The Downtime Logger has no bulk entry path, so these events either get double-entered (one at a time) or skipped entirely.

---

## Goal

Add a **DataParc Import** flow to the existing Downtime Logger that lets an operator upload a DataParc Excel export, classify each row in-app, and submit all records in one action — replacing the old Excel-to-reporting-system workflow.

---

## Scope

- Client-side Excel parsing (no backend changes)
- New `ImportScreen` with three stages: Upload → Review → Result
- Batch review table with per-row equipment/category/reason selection
- Submissions land in Firebase Storage in the same format as manual entries
- Two new record fields: `source` and `import_batch_id`
- No changes to existing single-entry flow, Firebase Storage rules, or BigQuery external table

---

## Architecture

The entire feature lives in `frontend/index.html`. SheetJS (`xlsx.js`) is added as a CDN script for client-side Excel parsing. Each submitted row is an individual JSON file written to Firebase Storage — identical path and format to manual entries. No new Cloud Functions, no new GCS paths, no schema changes.

```
Operator uploads .xlsx
        │
        ▼
SheetJS (CDN) — client-side parse
        │
        ▼
Column auto-detection (or manual picker if ambiguous)
        │
        ▼
Batch review table — operator classifies each row
        │
        ▼
"Submit all" → N parallel writes to Firebase Storage
        ├── records/us/2026-05-06T08-00-00-<uuid>.json
        ├── records/us/2026-05-06T14-00-00-<uuid>.json
        └── ...
        │
        ▼
Success screen — "N records imported"
```

---

## Screen Flow

```
HomeScreen
  └─ [Import from DataParc] button (alongside existing "Log downtime")
        └─ ImportScreen — Stage 1: Upload
        └─ ImportScreen — Stage 2: Review (batch table)
        └─ ImportScreen — Stage 3: Result
```

The import flow is a parallel path. The existing single-entry `FormScreen` is untouched.

---

## Stage 1 — Upload

- Drag-and-drop zone or tap-to-select for `.xlsx` files
- On file selection, SheetJS reads the file client-side and converts the first sheet to row objects
- **Column auto-detection:** scans header names for keywords `start`, `begin`, `from`, `end`, `stop`, `to` (case-insensitive) to identify the two timestamp columns
- If auto-detection is unambiguous → proceed directly to Stage 2
- If ambiguous (no recognisable headers, or more than 2 date columns) → show a **column picker**: two dropdowns ("Which column is Start Time?" / "Which column is End Time?") populated with the detected column names
- Rows where both timestamps are valid dates are kept. Invalid/blank rows are skipped silently. A count is shown: "2 rows skipped — could not read timestamps"

---

## Stage 2 — Batch Review Table

A scrollable table with one row per parsed event.

### Columns

| # | Start | End | Duration | Business Unit | Section | Equipment | Category | Reason | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 08:00 06/05 | 09:30 06/05 | 1h 30m | [BU ▾] | [—] | [—] | [Cat ▾] | [—] | ○ |

### Behaviour

- **Equipment selection** follows the same BU → Section → Equipment hierarchy as the single-entry form, compressed into inline dropdowns
- **"Apply to all rows"** option available on BU and Category — the two fields most likely to be uniform across a batch (e.g. all events are Alumina / Unplanned Maintenance). Applying sets that field only on rows where it is still empty — rows where the operator has already made a selection are not overwritten.
- A row turns **green with a checkmark** once equipment, category, and reason are all filled
- **"Submit all"** button is disabled until every row is fully classified
- Each row has a **delete (bin) icon** — removes that row from the batch if the operator decides it doesn't belong
- Duration is calculated as `end − start` and displayed read-only on each row

### Validation

- Required fields per row: equipment, category, reason
- Duration must be > 0 minutes (end time after start time) — rows failing this are flagged in red and must be deleted before submitting
- No minimum row count — operator can delete down to 1 row and submit

---

## Stage 3 — Result

After "Submit all":

- Success screen: **"N records imported successfully"**
- Breakdown list by equipment (e.g. "Reactor Vessel A — 3 events", "Feed Pump B — 2 events")
- "Back to home" button — returns to HomeScreen where the history list now reflects all imported records

---

## Data Model

Each row produces one JSON file in Firebase Storage. Format is identical to a manual entry with two additional fields:

```json
{
  "id": "<uuid>",
  "site": "Curtis Bay",
  "business_unit": "Alumina",
  "section": "Reaction",
  "equipment_id": "CB-AL-R-001",
  "equipment_name": "Reactor Vessel A",
  "category": "Unplanned",
  "category_detail": "Unplanned Maintenance",
  "reason": "Mechanical Failure",
  "duration_minutes": 90,
  "start_time": "2026-05-06T08:00:00.000Z",
  "end_time": "2026-05-06T09:30:00.000Z",
  "impact": "partial",
  "shift": "",
  "operator_name": "M. Reyes",
  "notes": "",
  "user_email": "m.reyes@grace.com",
  "source": "dataparc_import",
  "import_batch_id": "<single uuid shared across all rows in this upload>"
}
```

### New fields

| Field | Type | Description |
|---|---|---|
| `source` | string | `"dataparc_import"` for imported records, `"manual"` for single-entry (manual entries will be backfilled via query) |
| `import_batch_id` | string | UUID shared by all records from one upload — enables audit trail and Power BI filtering |
| `end_time` | string | ISO 8601 — already exists on manual entries (derived from start + duration), now explicitly set from Excel data |

---

## File Changes

| File | Change |
|---|---|
| `frontend/index.html` | Add SheetJS CDN script tag; add `ImportScreen` component; add "Import from DataParc" button to `HomeScreen`; add `source` field to manual entry records |

No other files change.

---

## What Is Out of Scope

- Automatic classification (AI/rule-based reason detection) — future enhancement
- Multi-sheet Excel support — first sheet only
- CSV support — `.xlsx` only for now
- Editing already-submitted import batches
- Progress bar for large files — 5–10 rows renders instantly
