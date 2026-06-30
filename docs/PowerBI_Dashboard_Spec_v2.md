# MedShare — Power BI Management Dashboard Specification (v2)

This version reflects the full built system: the **bidirectional marketplace** (surplus push +
request pull), the **two-step handshake**, **commission revenue**, and the new
**expired-stock waste registry**. It sits on the **same PostgreSQL tables** the app uses.

The app answers *"what do I do now?"*; this dashboard answers *"is the network healthy,
is the intervention working, and what is it worth?"*

**Connect:** Power BI Desktop → Get Data → PostgreSQL database → Server `localhost`
(or your cloud host), Database `pharma_redist` → **Import** mode (time intelligence and
sparklines need Import, not DirectQuery).

**Tables to load:** `pharmacies`, `drugs`, `inventory_batches`, `sales_daily`,
`expiry_risk_scores`, `demand_forecasts`, `redistribution_recommendations`, `transfers`,
`stock_requests` (new), `expired_stock` (new).

---

## 0. Data model (do this first)

### 0.1 Calculated date columns
Add these calculated columns (Modeling → New Column) so timestamps can join the Date table:
```DAX
-- on redistribution_recommendations
Created Date = DATE ( YEAR([created_at]), MONTH([created_at]), DAY([created_at]) )

-- on transfers
Created Date = DATE ( YEAR([created_at]), MONTH([created_at]), DAY([created_at]) )

-- on stock_requests
Created Date = DATE ( YEAR([created_at]), MONTH([created_at]), DAY([created_at]) )

-- on expired_stock
Logged Date = DATE ( YEAR([logged_at]), MONTH([logged_at]), DAY([logged_at]) )
```
`sales_daily[sale_date]`, `expiry_risk_scores[score_date]`, and `expired_stock[expiry_date]`
are already dates.

### 0.2 Date table
```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2025, 1, 1 ), DATE ( 2026, 12, 31 ) ),
    "Year", YEAR([Date]), "MonthNo", MONTH([Date]),
    "Month", FORMAT([Date],"MMM"), "YearMonth", FORMAT([Date],"YYYY-MM"),
    "Day", DAY([Date]), "Weekday", FORMAT([Date],"ddd")
)
```
Then: Table tools → **Mark as date table** → `[Date]`.

### 0.3 Relationships
Star around two dimensions (`pharmacies`, `drugs`) plus `Date`:

| From (many) | To (one) | Notes |
|---|---|---|
| `inventory_batches[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `inventory_batches[drug_id]` | `drugs[drug_id]` | active |
| `sales_daily[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `sales_daily[drug_id]` | `drugs[drug_id]` | active |
| `expiry_risk_scores[batch_id]` | `inventory_batches[batch_id]` | active |
| `redistribution_recommendations[batch_id]` | `inventory_batches[batch_id]` | active |
| `redistribution_recommendations[source_pharmacy_id]` | `pharmacies[pharmacy_id]` | active (source role) |
| `redistribution_recommendations[target_pharmacy_id]` | `pharmacies[pharmacy_id]` | inactive (USERELATIONSHIP for target) |
| `transfers[rec_id]` | `redistribution_recommendations[rec_id]` | active |
| `stock_requests[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `stock_requests[drug_id]` | `drugs[drug_id]` | active |
| `expired_stock[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `expired_stock[drug_id]` | `drugs[drug_id]` | active |
| `Date[Date]` | `sales_daily[sale_date]` | active |
| `Date[Date]` | `expiry_risk_scores[score_date]` | active |
| `Date[Date]` | `transfers[Created Date]` | active |
| `Date[Date]` | `expired_stock[Logged Date]` | inactive (USERELATIONSHIP where needed) |

---

## 1. Measures library

Create one blank table `_Measures` (Enter Data → empty) and put all measures there.

### 1.1 Network base
```DAX
Active Pharmacies = DISTINCTCOUNT ( pharmacies[pharmacy_id] )
Real Pharmacies   = CALCULATE ( [Active Pharmacies], pharmacies[is_synthetic] = FALSE )
Total Batches     = CALCULATE ( COUNTROWS ( inventory_batches ), inventory_batches[is_expired] = FALSE, inventory_batches[quantity] > 0 )
Live Stock Value  = SUMX ( FILTER ( inventory_batches, inventory_batches[is_expired] = FALSE ), inventory_batches[quantity] * inventory_batches[unit_price] )
```

### 1.2 Expiry risk (latest scoring snapshot)
```DAX
Latest Score Date = CALCULATE ( MAX ( expiry_risk_scores[score_date] ) )

At-Risk Batches =
CALCULATE ( COUNTROWS ( expiry_risk_scores ),
    expiry_risk_scores[score_date] = [Latest Score Date],
    expiry_risk_scores[risk_tier] IN { "High", "Critical" } )

Critical Batches =
CALCULATE ( COUNTROWS ( expiry_risk_scores ),
    expiry_risk_scores[score_date] = [Latest Score Date],
    expiry_risk_scores[risk_tier] = "Critical" )

Value At Risk =
SUMX (
    FILTER ( expiry_risk_scores, expiry_risk_scores[score_date] = [Latest Score Date]
             && expiry_risk_scores[risk_tier] IN { "High", "Critical" } ),
    RELATED ( inventory_batches[quantity] ) * RELATED ( inventory_batches[unit_price] ) )
```

### 1.3 Redistribution activity (note: now split by origin)
```DAX
Recs Generated  = COUNTROWS ( redistribution_recommendations )
Recs Surplus    = CALCULATE ( [Recs Generated], redistribution_recommendations[origin] = "SURPLUS" )
Recs Request    = CALCULATE ( [Recs Generated], redistribution_recommendations[origin] = "REQUEST" )

Offers Sent     = CALCULATE ( [Recs Generated], redistribution_recommendations[status] IN { "OFFERED","ACCEPTED","DECLINED" } )
Offers Accepted = CALCULATE ( [Recs Generated], redistribution_recommendations[status] = "ACCEPTED" )
Offers Declined = CALCULATE ( [Recs Generated], redistribution_recommendations[status] = "DECLINED" )

Acceptance Rate =
DIVIDE ( [Offers Accepted], [Offers Accepted] + [Offers Declined] )
```

### 1.4 Requests (the new pull side)
```DAX
Requests Posted    = COUNTROWS ( stock_requests )
Requests Open      = CALCULATE ( [Requests Posted], stock_requests[status] = "OPEN" )
Requests Matched   = CALCULATE ( [Requests Posted], stock_requests[status] = "MATCHED" )
Requests Fulfilled = CALCULATE ( [Requests Posted], stock_requests[status] = "FULFILLED" )
Requests Cancelled = CALCULATE ( [Requests Posted], stock_requests[status] = "CANCELLED" )

Request Fulfilment Rate =
DIVIDE ( [Requests Fulfilled], [Requests Fulfilled] + [Requests Cancelled] + [Requests Open] )
```

### 1.5 Transfers, value rescued & commission (the revenue layer)
```DAX
Completed Transfers = CALCULATE ( COUNTROWS ( transfers ), transfers[status] = "ACCEPTED" )
Units Redistributed = SUM ( transfers[agreed_quantity] )
Gross Transfer Value = SUM ( transfers[gross_value] )
Value Rescued = SUM ( transfers[gross_value] )           -- value moved instead of expiring
Platform Revenue = SUM ( transfers[commission_amount] )  -- the business model in one number
Avg Commission % = DIVIDE ( [Platform Revenue], [Gross Transfer Value] )
```

### 1.6 Waste incurred (the new expired_stock registry)
```DAX
Expired Batches   = COUNTROWS ( expired_stock )
Units Expired     = SUM ( expired_stock[units_expired] )
Waste Incurred    = SUM ( expired_stock[value_lost] )    -- Naira actually lost to expiry

-- Headline framing: prevented vs incurred
Total Loss Exposure = [Waste Incurred] + [Value Rescued]
Waste Prevented Rate = DIVIDE ( [Value Rescued], [Total Loss Exposure] )
```
> Honesty note for the panel: `Waste Prevented Rate` here is an **operational, in-app ratio**
> (rescued ÷ rescued+incurred). It is NOT the headline evaluation figure. The authoritative
> waste-reduction result (~51% vs the realistic baseline) comes from `evaluate.py` / Chapter 4,
> not from this dashboard. Label this tile "Operational rescue ratio," not "waste reduction."

---

## 2. Time-intelligence measures
```DAX
Revenue MTD = TOTALMTD ( [Platform Revenue], 'Date'[Date] )
Rescued YTD = TOTALYTD ( [Value Rescued], 'Date'[Date] )
Waste MoM =
VAR Cur = [Waste Incurred]
VAR Prev = CALCULATE ( [Waste Incurred], DATEADD ( 'Date'[Date], -1, MONTH ) )
RETURN DIVIDE ( Cur - Prev, Prev )
Rescued 30d = CALCULATE ( [Value Rescued], DATESINPERIOD ( 'Date'[Date], MAX('Date'[Date]), -30, DAY ) )
```

---

## 3. Pages

Common **slicers** on every page (View → Sync slicers): `Date[YearMonth]`,
`pharmacies[area]`, `drugs[category]`, and a `pharmacies[is_synthetic]` slicer
(so you can show **real survey pharmacies only** — a strong viva move).

### PAGE 1 — Network Overview
The "is the network healthy?" page.
- **KPI cards (top row):** Active Pharmacies · Total Batches · Live Stock Value (₦) · At-Risk Batches · **Platform Revenue (₦)**.
- **Map:** pharmacies plotted by latitude/longitude, bubble size = Live Stock Value, colour = has Critical batches (red) vs not. Add an `is_synthetic` legend so real (PH) vs synthetic (SY) is visible.
- **Line chart:** Value Rescued and Waste Incurred over time (two lines) — the core story in one visual.
- **Donut:** recommendations by origin (Surplus vs Request) — shows the marketplace is bidirectional.

### PAGE 2 — Expiry Risk (Model 1)
- **KPI cards:** At-Risk Batches · Critical Batches · Value At Risk (₦).
- **Map:** pharmacies with High/Critical batches, colour-coded by worst tier.
- **Stacked bar:** at-risk batches by drug category, segmented by tier.
- **Line:** weekly count of batches entering High/Critical over time.
- **Table:** top at-risk batches (pharmacy, drug, days-to-expiry, value, tier).

### PAGE 3 — Marketplace Activity (Model 3 + handshake)
The "is the matching working?" page — now covers **both directions and the handshake**.
- **KPI cards:** Recs Generated · Offers Sent · Acceptance Rate (%) · Completed Transfers.
- **Funnel:** Recommended → Offered → Accepted → Completed (shows where deals drop off).
- **Clustered column:** recommendations by origin (Surplus vs Request) per week.
- **Requests panel:** cards for Requests Posted / Open / Matched / Fulfilled / Cancelled, plus Request Fulfilment Rate.
- **Table:** recent transfers (source → target, drug, qty, agreed price, **commission**, status).

### PAGE 4 — Impact, Revenue & Waste
The "what is it worth, and what still slips through?" page — the headline for stakeholders.
- **KPI cards:** Value Rescued (₦) · Units Redistributed · **Platform Revenue (₦)** · **Waste Incurred (₦)** · Operational Rescue Ratio (%).
- **Side-by-side bars:** Value Rescued vs Waste Incurred by drug category — shows where redistribution wins and where waste still concentrates.
- **Line (cumulative):** cumulative Value Rescued and cumulative Platform Revenue over time.
- **Waste registry table (from `expired_stock`):** pharmacy, drug, units expired, value lost, expiry date — the honest record of what still lapsed.
- **Card + caption:** Avg Commission % with a note that revenue is earned only on completed transfers (the incentive-aligned business model).

### PAGE 5 (optional) — Business Model View
A single page tying the commercial story together for a business-school panel.
- **Platform Revenue** (total + MTD + YTD).
- **Revenue by area / by drug category** (where the value is).
- **Revenue vs Cost note:** a text box stating the lean cost base (open-source stack, hosting + messaging) and that profitability is a pilot question — keeps it honest.

---

## 4. Scope guidance
For the **thesis**, build **Page 1 + Page 4** first — together they prove the management layer
exists, is fed by the live database, and shows both impact (rescued) and honesty (incurred).
Add Pages 2, 3, and 5 if time allows; for the live demo, Page 4 is the one to show stakeholders.

## 5. What changed from v1
- Added `stock_requests` and `expired_stock` tables to the model.
- New measures: request/pull funnel, **Platform Revenue** and **Avg Commission %**,
  and the **Waste Incurred** registry measures.
- Page 3 renamed to **Marketplace Activity** and now shows both origins + the handshake funnel.
- Page 4 expanded to **Impact, Revenue & Waste** (rescued vs incurred, plus the waste registry table).
- New optional Page 5 for the business-model view.
- Clear labelling so the dashboard's operational rescue ratio is not confused with the
  Chapter 4 evaluation figure.
