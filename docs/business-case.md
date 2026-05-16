# Plant Downtime Logger — Business Case

## The Problem

W.R. Grace operates 18 manufacturing plants across four continents.
Downtime is tracked inconsistently: most sites use Excel spreadsheets
uploaded to a central system; one site uses a basic web app. There is
no uniform taxonomy, no real-time visibility, and no cross-site
comparison. Operations directors make decisions on delayed, incomplete,
and non-comparable data.

**Three specific gaps:**

1. **No Planned vs Unplanned split** — the standard OEE input is
   missing. Sites cannot distinguish reactive maintenance from
   scheduled stops.

2. **No MTBF visibility across plants** — if REACTOR-A fails repeatedly
   across three sites, no one sees the pattern. Each site diagnoses in
   isolation.

3. **Manual reconciliation** — site coordinators spend estimated hours
   per week reformatting spreadsheets before data can be aggregated.

## Quantified Impact

| Input | Value |
|---|---|
| Average unplanned downtime event | 2 hours |
| Production value | $X,XXX / hour (fill in per site) |
| Unplanned events per site per week | ~5 |
| Sites currently without standardised logging | 17 of 18 |

Annual unplanned downtime hours across affected sites = ~8,840 hours.
Without standardised logging, this figure cannot be calculated,
reported, or acted on.

## The Solution

A standardised global downtime logging system:
- One URL for all 300 operators worldwide
- Real-time cross-site visibility in Power BI
- Planned vs Unplanned classification at point of entry
- MTBF analysis per equipment type across all sites
- Each new plant added with 2 lines of configuration

## Cost Comparison

| Option | Annual cost | Notes |
|---|---|---|
| **This system** | **~$240/year** | All 18 plants, 300 users |
| Power Apps Premium | $18,000–72,000/year | Requires Premium licence for SQL connectivity |
| Power Apps per-app | $18,000/year | $5/user/month × 300 users |

## The Ask

COE funds migration of this proof-of-concept from personal Azure
subscription to W.R. Grace Azure tenant. IT takes infrastructure
ownership. Operations team owns the data.

**Handoff is designed in from day one** — Terraform state, Entra ID,
and CI/CD pipeline all migrate with one config change each.
