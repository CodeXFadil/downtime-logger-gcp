# COE Demo Script — 5 Minutes

**Setup before the meeting:**
- Traffic Manager URL open in two browser tabs (one normal, one incognito)
- Power BI global dashboard open in a third tab
- `terraform.tfvars` open in VS Code, ready to show the 2-line config

---

## 0:00 — Open the app

Open the Traffic Manager URL.
- Point out the site badge: "Curtis Bay (East US)" — auto-detected, no manual config.
- "This is the same URL used by operators in Malaysia, Brazil, Germany — one URL, five regions."
- Entra SSO fired silently — no login screen because we're already authenticated.

## 1:00 — Log a downtime event

Fill in the form:
1. Click **UNPLANNED** — reasons filter to the unplanned list
2. Select **Mechanical Failure**
3. Select **REACTOR-A — Reactor Vessel A**
4. Shift: **Morning**
5. Duration: **90**
6. Operator name: your name
7. Hit **Submit Downtime Record**

Point out: record appears instantly in the Recent Incidents table on the right.

## 2:45 — Switch to Kuantan view

Open the incognito tab. The Traffic Manager URL now routes to Southeast Asia
(or use a VPN / mock the region by calling the Malaysia Function App URL directly).

Point out: "Curtis Bay record is visible here too. One database, two continents,
real-time." Both site tags are visible in the table.

## 3:30 — Open Power BI

Open the global dashboard tab.
- Show vw_downtime_global: Curtis Bay and Kuantan side by side.
- Show vw_downtime_by_equipment: MTBF chart for REACTOR-A.
- "Any operations director can see this right now, from any device."

## 4:30 — The scalability moment

Open VS Code with `terraform.tfvars` visible.

Say: "You asked about our other 16 plants. Adding Worms, Germany looks like this."

Type:
```
compute_regions = {
  us-north = "East US"
  malaysia  = "Southeast Asia"
  worms     = "West Europe"       ← add this line
}
site_names = {
  ...
  worms = "Worms, Germany"        ← add this line
}
```

"Run terraform apply and the full regional stack — networking, Functions, Key Vault,
Traffic Manager endpoint — is provisioned automatically. The operators in Worms log
in with their existing W.R. Grace credentials. Their data appears in the global view
immediately."

---

**Expected questions and answers:**

| Question | Answer |
|---|---|
| "Who maintains this?" | IT owns the Azure infrastructure after handoff. Terraform is the source of truth — no manual Portal clicks. |
| "Why not Power Apps?" | Our M365 licence doesn't include Premium, which is required to connect to Azure SQL. Premium costs $18,000–72,000/year for 300 users. This system costs $240/year. |
| "Why Python?" | It's my domain language — readable and auditable. The architecture is language-agnostic; IT can rewrite in C# without touching infrastructure. |
| "What about offline?" | This POC is browser-based. A future version could use a Progressive Web App (PWA) for offline capture with sync on reconnect — that's a Phase 2 item. |
