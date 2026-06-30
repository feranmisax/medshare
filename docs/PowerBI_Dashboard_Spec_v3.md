# MedShare — Power BI Management Dashboard Specification (v3, page-by-page)

Each page below is self-contained: it lists every visual on the page, the exact fields/measures
that go into each visual, and the DAX for any measure that page needs. Build pages top to bottom.

The dashboard sits on the **same PostgreSQL tables** the app uses. The app answers
*"what do I do now?"*; this dashboard answers *"is the network healthy, is the intervention
working, and what is it worth?"*

**Connect:** Power BI Desktop → Get Data → PostgreSQL → Server `localhost` (or your Neon host),
Database `pharma_redist` → **Import** mode. Load: `pharmacies`, `drugs`, `inventory_batches`,
`sales_daily`, `expiry_risk_scores`, `demand_forecasts`, `redistribution_recommendations`,
`transfers`, `stock_requests`, `expired_stock`.

---

## 0. One-time model setup (do this before any page)

**Calculated date columns** (Modeling → New Column):
```DAX
-- redistribution_recommendations
Created Date = DATE(YEAR([created_at]),MONTH([created_at]),DAY([created_at]))
-- transfers
Created Date = DATE(YEAR([created_at]),MONTH([created_at]),DAY([created_at]))
-- stock_requests
Created Date = DATE(YEAR([created_at]),MONTH([created_at]),DAY([created_at]))
-- expired_stock
Logged Date  = DATE(YEAR([logged_at]),MONTH([logged_at]),DAY([logged_at]))
```

**Date table** (New Table), then Table tools → Mark as date table → `[Date]`:
```DAX
Date = ADDCOLUMNS ( CALENDAR(DATE(2025,1,1),DATE(2026,12,31)),
  "Year",YEAR([Date]),"MonthNo",MONTH([Date]),"Month",FORMAT([Date],"MMM"),
  "YearMonth",FORMAT([Date],"YYYY-MM"),"Day",DAY([Date]),"Weekday",FORMAT([Date],"ddd") )
```

**Relationships:** `inventory_batches`,`sales_daily`,`stock_requests`,`expired_stock` →
`pharmacies[pharmacy_id]` and `drugs[drug_id]`; `expiry_risk_scores[batch_id]` and
`redistribution_recommendations[batch_id]` → `inventory_batches[batch_id]`;
`redistribution_recommendations[source_pharmacy_id]` → `pharmacies` (active),
`[target_pharmacy_id]` → `pharmacies` (inactive); `transfers[rec_id]` →
`redistribution_recommendations[rec_id]`; `Date[Date]` → `sales_daily[sale_date]`,
`expiry_risk_scores[score_date]`, `transfers[Created Date]`.

**Shared slicers** (put on each page; View → Sync slicers): `Date[YearMonth]`,
`pharmacies[area]`, `drugs[category]`, `pharmacies[is_synthetic]`.

Create one empty table `_Measures` to hold all measures below.

---

## PAGE 1 — Network Overview
*"Is the network healthy?"*

### Measures this page needs
```DAX
Active Pharmacies = DISTINCTCOUNT ( pharmacies[pharmacy_id] )
Total Batches = CALCULATE ( COUNTROWS(inventory_batches), inventory_batches[is_expired]=FALSE, inventory_batches[quantity]>0 )
Live Stock Value = SUMX ( FILTER(inventory_batches, inventory_batches[is_expired]=FALSE), inventory_batches[quantity]*inventory_batches[unit_price] )
Latest Score Date = CALCULATE ( MAX(expiry_risk_scores[score_date]) )
At-Risk Batches = CALCULATE ( COUNTROWS(expiry_risk_scores), expiry_risk_scores[score_date]=[Latest Score Date], expiry_risk_scores[risk_tier] IN {"High","Critical"} )
Platform Revenue = SUM ( transfers[commission_amount] )
Value Rescued = SUM ( transfers[gross_value] )
Waste Incurred = SUM ( expired_stock[value_lost] )
```

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| KPI: Active Pharmacies | Card | `[Active Pharmacies]` |
| KPI: Total Batches | Card | `[Total Batches]` |
| KPI: Live Stock Value | Card | `[Live Stock Value]` (format ₦, thousands) |
| KPI: At-Risk Batches | Card | `[At-Risk Batches]` |
| KPI: Platform Revenue | Card | `[Platform Revenue]` (format ₦) |
| Pharmacy map | Map (Azure/filled) | Latitude = `pharmacies[latitude]`, Longitude = `pharmacies[longitude]`, Bubble size = `[Live Stock Value]`, Legend = `pharmacies[is_synthetic]` |
| Rescued vs Waste over time | Line chart | Axis = `Date[YearMonth]`, Values = `[Value Rescued]`, `[Waste Incurred]` |
| Recommendations by origin | Donut | Legend = `redistribution_recommendations[origin]`, Values = count of `rec_id` |

---

## PAGE 2 — Expiry Risk (Model 1)
*"Where is stock about to be lost?"*

### Measures this page needs
```DAX
Critical Batches = CALCULATE ( COUNTROWS(expiry_risk_scores), expiry_risk_scores[score_date]=[Latest Score Date], expiry_risk_scores[risk_tier]="Critical" )
Value At Risk = SUMX ( FILTER(expiry_risk_scores, expiry_risk_scores[score_date]=[Latest Score Date] && expiry_risk_scores[risk_tier] IN {"High","Critical"}), RELATED(inventory_batches[quantity])*RELATED(inventory_batches[unit_price]) )
```
(reuses `[At-Risk Batches]`, `[Latest Score Date]` from Page 1)

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| KPI: At-Risk Batches | Card | `[At-Risk Batches]` |
| KPI: Critical Batches | Card | `[Critical Batches]` |
| KPI: Value At Risk | Card | `[Value At Risk]` (₦) |
| Risk map | Map | Lat/Long = `pharmacies`, Legend = `expiry_risk_scores[risk_tier]` (filter to High/Critical) |
| At-risk by category | Stacked bar | Axis = `drugs[category]`, Legend = `expiry_risk_scores[risk_tier]`, Value = count of batches |
| Risk trend | Line | Axis = `expiry_risk_scores[score_date]`, Value = `[At-Risk Batches]` |
| Top at-risk batches | Table | `pharmacies[pharmacy_id]`, `drugs[name]`, `inventory_batches[expiry_date]`, `inventory_batches[quantity]`, `[Value At Risk]`, `expiry_risk_scores[risk_tier]` |

---

## PAGE 3 — Marketplace Activity (Model 3 + handshake)
*"Is the matching and the handshake working, in both directions?"*

### Measures this page needs
```DAX
Recs Generated  = COUNTROWS ( redistribution_recommendations )
Recs Surplus    = CALCULATE ( [Recs Generated], redistribution_recommendations[origin]="SURPLUS" )
Recs Request    = CALCULATE ( [Recs Generated], redistribution_recommendations[origin]="REQUEST" )
Offers Sent     = CALCULATE ( [Recs Generated], redistribution_recommendations[status] IN {"OFFERED","ACCEPTED","DECLINED"} )
Offers Accepted = CALCULATE ( [Recs Generated], redistribution_recommendations[status]="ACCEPTED" )
Offers Declined = CALCULATE ( [Recs Generated], redistribution_recommendations[status]="DECLINED" )
Acceptance Rate = DIVIDE ( [Offers Accepted], [Offers Accepted]+[Offers Declined] )
Completed Transfers = CALCULATE ( COUNTROWS(transfers), transfers[status]="ACCEPTED" )
Requests Posted    = COUNTROWS ( stock_requests )
Requests Open      = CALCULATE ( [Requests Posted], stock_requests[status]="OPEN" )
Requests Matched   = CALCULATE ( [Requests Posted], stock_requests[status]="MATCHED" )
Requests Fulfilled = CALCULATE ( [Requests Posted], stock_requests[status]="FULFILLED" )
Requests Cancelled = CALCULATE ( [Requests Posted], stock_requests[status]="CANCELLED" )
Request Fulfilment Rate = DIVIDE ( [Requests Fulfilled], [Requests Fulfilled]+[Requests Cancelled]+[Requests Open] )
```

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| KPI: Recs Generated | Card | `[Recs Generated]` |
| KPI: Offers Sent | Card | `[Offers Sent]` |
| KPI: Acceptance Rate | Card | `[Acceptance Rate]` (%) |
| KPI: Completed Transfers | Card | `[Completed Transfers]` |
| Handshake funnel | Funnel | Values, in order: `[Recs Generated]`, `[Offers Sent]`, `[Offers Accepted]`, `[Completed Transfers]` |
| Recs by origin per month | Clustered column | Axis = `Date[YearMonth]`, Values = `[Recs Surplus]`, `[Recs Request]` |
| Requests status | Multi-row card | `[Requests Posted]`, `[Requests Open]`, `[Requests Matched]`, `[Requests Fulfilled]`, `[Requests Cancelled]`, `[Request Fulfilment Rate]` |
| Recent transfers | Table | source `pharmacies[pharmacy_id]`, target (via target rel), `drugs[name]`, `transfers[agreed_quantity]`, `transfers[agreed_price]`, `transfers[commission_amount]`, `redistribution_recommendations[status]` |

---

## PAGE 4 — Impact, Revenue & Waste
*"What is it worth, and what still slips through?"* (the stakeholder headline page)

### Measures this page needs
```DAX
Units Redistributed = SUM ( transfers[agreed_quantity] )
Gross Transfer Value = SUM ( transfers[gross_value] )
Avg Commission % = DIVIDE ( [Platform Revenue], [Gross Transfer Value] )
Units Expired = SUM ( expired_stock[units_expired] )
Operational Rescue Ratio = DIVIDE ( [Value Rescued], [Value Rescued]+[Waste Incurred] )
Rescued YTD = TOTALYTD ( [Value Rescued], 'Date'[Date] )
Revenue MTD = TOTALMTD ( [Platform Revenue], 'Date'[Date] )
```
(reuses `[Value Rescued]`, `[Platform Revenue]`, `[Waste Incurred]`)

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| KPI: Value Rescued | Card | `[Value Rescued]` (₦) |
| KPI: Units Redistributed | Card | `[Units Redistributed]` |
| KPI: Platform Revenue | Card | `[Platform Revenue]` (₦) |
| KPI: Waste Incurred | Card | `[Waste Incurred]` (₦) |
| KPI: Operational Rescue Ratio | Card | `[Operational Rescue Ratio]` (%) — label it "Operational rescue ratio," NOT "waste reduction" |
| Rescued vs Waste by category | Clustered bar | Axis = `drugs[category]`, Values = `[Value Rescued]`, `[Waste Incurred]` |
| Cumulative value & revenue | Line (running total) | Axis = `Date[Date]`, Values = `[Value Rescued]`, `[Platform Revenue]` (set both to running total via quick measure) |
| Waste registry | Table | `pharmacies[pharmacy_id]`, `drugs[name]`, `expired_stock[units_expired]`, `expired_stock[value_lost]`, `expired_stock[expiry_date]` |
| Commission note | Text box | "Platform earns only on completed transfers — Avg commission `[Avg Commission %]`." |

> **Honesty label (important):** the Operational Rescue Ratio is a live in-app ratio
> (rescued ÷ rescued+incurred). It is NOT the Chapter 4 evaluation figure (~51% vs the
> realistic baseline), which comes from `evaluate.py` under Monte Carlo. Keep the wording
> distinct so the two are never confused.

---

## PAGE 5 (optional) — Business Model View
*"How does this sustain itself?"* (for the business-school angle)

### Measures this page needs
(reuses `[Platform Revenue]`, `[Revenue MTD]`, `[Rescued YTD]`, `[Avg Commission %]`)

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| KPI: Platform Revenue (total) | Card | `[Platform Revenue]` |
| KPI: Revenue MTD | Card | `[Revenue MTD]` |
| KPI: Rescued YTD | Card | `[Rescued YTD]` |
| Revenue by area | Bar | Axis = `pharmacies[area]`, Value = `[Platform Revenue]` |
| Revenue by category | Bar | Axis = `drugs[category]`, Value = `[Platform Revenue]` |
| Cost-base note | Text box | "Lean cost base: open-source stack + cloud hosting + messaging gateway. A small per-transfer commission funds the platform; profitability is a pilot question." |

---

## Build priority
For the thesis, build **Page 1 + Page 4** first (they prove the management layer is live and
show impact + honesty). Add Pages 2, 3, 5 if time allows. For the live demo, lead with Page 4.

## Format tips
- Format all ₦ cards as currency with thousands separators; ratios as percentage, 0–1 decimals.
- Use the same green as the app (`#0F6E5C`) for the accent colour to keep brand consistency.
- For the "target" pharmacy in transfer/recommendation visuals, use `USERELATIONSHIP` in a
  measure if you need to count by target rather than source.
