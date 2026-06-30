# MedShare — Power BI Management Dashboard Specification (v4, page-by-page, management edition)

Each page is self-contained: its visuals, the exact fields/measures each visual uses, and the
DAX it needs are grouped together. This edition adds a full **time-intelligence layer**
(month-on-month deltas, running totals, trends) and **sparklines on the KPI cards**, framed for
a **business / management** audience: every headline number carries a direction and a trend,
not just a level.

The dashboard sits on the **same PostgreSQL tables** the app uses. The app answers
*"what do I do now?"*; this dashboard answers the executive questions: *is the network growing,
is the intervention working, is it creating value, and is it on a path to sustainability?*

**Connect:** Power BI Desktop → Get Data → PostgreSQL → Server `localhost` (or your Neon host),
Database `pharma_redist` → **Import** mode (time intelligence and sparklines REQUIRE Import).
Load: `pharmacies`, `drugs`, `inventory_batches`, `sales_daily`, `expiry_risk_scores`,
`demand_forecasts`, `redistribution_recommendations`, `transfers`, `stock_requests`, `expired_stock`.

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
  "YearMonth",FORMAT([Date],"YYYY-MM"),"MonthStart",DATE(YEAR([Date]),MONTH([Date]),1),
  "Day",DAY([Date]),"Weekday",FORMAT([Date],"ddd") )
```

**Relationships:** `inventory_batches`,`sales_daily`,`stock_requests`,`expired_stock` →
`pharmacies[pharmacy_id]` and `drugs[drug_id]`; `expiry_risk_scores[batch_id]` and
`redistribution_recommendations[batch_id]` → `inventory_batches[batch_id]`;
`redistribution_recommendations[source_pharmacy_id]` → `pharmacies` (active),
`[target_pharmacy_id]` → `pharmacies` (inactive); `transfers[rec_id]` →
`redistribution_recommendations[rec_id]`; `Date[Date]` → `transfers[Created Date]` (active),
plus `sales_daily[sale_date]`, `expiry_risk_scores[score_date]`.

**Shared slicers** (each page; View → Sync slicers): `Date[YearMonth]`, `pharmacies[area]`,
`drugs[category]`, `pharmacies[is_synthetic]`.

Create one empty table `_Measures` for all measures.

### How sparklines work (read once)
In a **Card (new)** or **Table/Matrix**, select the field → Format → **Add sparkline** →
X axis = `Date[MonthStart]`, Y axis = the measure. Power BI draws a mini line in the card.
So every KPI below that says "with sparkline" just needs its base measure plus a date axis —
no special measure required for the line itself. The **delta %** beside it IS a measure (the
MoM measures below), shown as a second card or a callout.

---

## PAGE 1 — Executive Summary
*"Is the network growing and creating value?"* — the one-screen board view.

### Measures this page needs
```DAX
-- levels
Active Pharmacies = DISTINCTCOUNT ( pharmacies[pharmacy_id] )
Live Stock Value  = SUMX ( FILTER(inventory_batches, inventory_batches[is_expired]=FALSE), inventory_batches[quantity]*inventory_batches[unit_price] )
Value Rescued     = SUM ( transfers[gross_value] )
Platform Revenue  = SUM ( transfers[commission_amount] )
Waste Incurred    = SUM ( expired_stock[value_lost] )

-- time intelligence (month-on-month deltas for the executive cards)
Revenue MoM % =
VAR Cur = [Platform Revenue]
VAR Prev = CALCULATE ( [Platform Revenue], DATEADD('Date'[Date],-1,MONTH) )
RETURN DIVIDE ( Cur - Prev, Prev )

Rescued MoM % =
VAR Cur = [Value Rescued]
VAR Prev = CALCULATE ( [Value Rescued], DATEADD('Date'[Date],-1,MONTH) )
RETURN DIVIDE ( Cur - Prev, Prev )

Waste MoM % =
VAR Cur = [Waste Incurred]
VAR Prev = CALCULATE ( [Waste Incurred], DATEADD('Date'[Date],-1,MONTH) )
RETURN DIVIDE ( Cur - Prev, Prev )   -- for waste, DOWN is good; colour-reverse this card

Pharmacies MoM = [Active Pharmacies] - CALCULATE ( [Active Pharmacies], DATEADD('Date'[Date],-1,MONTH) )

-- running totals for the trend strip
Revenue Running = CALCULATE ( [Platform Revenue], FILTER ( ALLSELECTED('Date'[Date]), 'Date'[Date] <= MAX('Date'[Date]) ) )
Rescued Running = CALCULATE ( [Value Rescued],   FILTER ( ALLSELECTED('Date'[Date]), 'Date'[Date] <= MAX('Date'[Date]) ) )
```

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| Active Pharmacies | KPI card **with sparkline** | Value `[Active Pharmacies]`, sparkline axis `Date[MonthStart]`, delta `[Pharmacies MoM]` |
| Live Stock Value | KPI card with sparkline | Value `[Live Stock Value]` (₦), sparkline over `Date[MonthStart]` |
| Value Rescued | KPI card with sparkline + delta | Value `[Value Rescued]` (₦), delta `[Rescued MoM %]` (green ↑) |
| Platform Revenue | KPI card with sparkline + delta | Value `[Platform Revenue]` (₦), delta `[Revenue MoM %]` (green ↑) |
| Waste Incurred | KPI card with sparkline + delta | Value `[Waste Incurred]` (₦), delta `[Waste MoM %]` (**reverse colours: down = green**) |
| Cumulative value & revenue | Area/line | Axis `Date[MonthStart]`, Values `[Rescued Running]`, `[Revenue Running]` |
| Rescued vs Waste over time | Line | Axis `Date[YearMonth]`, Values `[Value Rescued]`, `[Waste Incurred]` |
| Network map | Map | Lat/Long `pharmacies`, size `[Live Stock Value]`, legend `pharmacies[is_synthetic]` |

**Management read:** top row = "where are we and which way are we moving"; trend strip = "is the
trajectory right"; map = "where is the value concentrated." A board member should grasp the
whole story in 10 seconds from this page alone.

---

## PAGE 2 — Expiry Risk (Model 1)
*"How much capital is exposed, and is exposure rising or falling?"*

### Measures this page needs
```DAX
Latest Score Date = CALCULATE ( MAX(expiry_risk_scores[score_date]) )
At-Risk Batches = CALCULATE ( COUNTROWS(expiry_risk_scores), expiry_risk_scores[score_date]=[Latest Score Date], expiry_risk_scores[risk_tier] IN {"High","Critical"} )
Critical Batches = CALCULATE ( COUNTROWS(expiry_risk_scores), expiry_risk_scores[score_date]=[Latest Score Date], expiry_risk_scores[risk_tier]="Critical" )
Value At Risk = SUMX ( FILTER(expiry_risk_scores, expiry_risk_scores[score_date]=[Latest Score Date] && expiry_risk_scores[risk_tier] IN {"High","Critical"}), RELATED(inventory_batches[quantity])*RELATED(inventory_batches[unit_price]) )

Value At Risk MoM % =
VAR Cur = [Value At Risk]
VAR Prev = CALCULATE ( [Value At Risk], DATEADD('Date'[Date],-1,MONTH) )
RETURN DIVIDE ( Cur - Prev, Prev )   -- down = good; reverse colours
```

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| At-Risk Batches | KPI card with sparkline | `[At-Risk Batches]`, sparkline over `expiry_risk_scores[score_date]` |
| Critical Batches | KPI card | `[Critical Batches]` |
| Value At Risk | KPI card with delta | `[Value At Risk]` (₦), delta `[Value At Risk MoM %]` (reverse colours) |
| Risk map | Map | Lat/Long `pharmacies`, legend `expiry_risk_scores[risk_tier]` (High/Critical only) |
| At-risk by category | Stacked bar | Axis `drugs[category]`, legend `risk_tier`, value batch count |
| Exposure trend | Line | Axis `expiry_risk_scores[score_date]`, value `[Value At Risk]` |
| Top at-risk batches | Table | `pharmacies[pharmacy_id]`, `drugs[name]`, `inventory_batches[expiry_date]`, `inventory_batches[quantity]`, `[Value At Risk]`, `risk_tier` |

**Management read:** Value At Risk is working capital one step from being written off; the MoM
delta tells management whether the platform is shrinking that exposure over time.

---

## PAGE 3 — Marketplace Activity (Model 3 + handshake)
*"Is the two-sided marketplace converting, and is throughput growing?"*

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

Acceptance Rate MoM pts =
VAR Cur = [Acceptance Rate]
VAR Prev = CALCULATE ( [Acceptance Rate], DATEADD('Date'[Date],-1,MONTH) )
RETURN Cur - Prev   -- percentage-point change

Transfers MoM % =
VAR Cur = [Completed Transfers]
VAR Prev = CALCULATE ( [Completed Transfers], DATEADD('Date'[Date],-1,MONTH) )
RETURN DIVIDE ( Cur - Prev, Prev )

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
| Recs Generated | KPI card with sparkline | `[Recs Generated]`, sparkline over `Date[MonthStart]` |
| Offers Sent | KPI card | `[Offers Sent]` |
| Acceptance Rate | KPI card with delta | `[Acceptance Rate]` (%), delta `[Acceptance Rate MoM pts]` |
| Completed Transfers | KPI card with delta | `[Completed Transfers]`, delta `[Transfers MoM %]` |
| Handshake funnel | Funnel | ordered: `[Recs Generated]`, `[Offers Sent]`, `[Offers Accepted]`, `[Completed Transfers]` |
| Recs by origin per month | Clustered column | Axis `Date[YearMonth]`, values `[Recs Surplus]`, `[Recs Request]` |
| Requests status | Multi-row card | `[Requests Posted]`,`[Requests Open]`,`[Requests Matched]`,`[Requests Fulfilled]`,`[Requests Cancelled]`,`[Request Fulfilment Rate]` |
| Recent transfers | Table | source `pharmacies[pharmacy_id]`, target, `drugs[name]`, `transfers[agreed_quantity]`, `transfers[agreed_price]`, `transfers[commission_amount]`, `status` |

**Management read:** the funnel is the conversion story (offer → accept → complete); the
acceptance-rate trend is the leading indicator of marketplace health; the origin split proves
demand is being served from both sides.

---

## PAGE 4 — Impact, Revenue & Waste
*"What is it worth, what's the run-rate, and what still slips through?"* (stakeholder headline)

### Measures this page needs
```DAX
Units Redistributed = SUM ( transfers[agreed_quantity] )
Gross Transfer Value = SUM ( transfers[gross_value] )
Avg Commission % = DIVIDE ( [Platform Revenue], [Gross Transfer Value] )
Units Expired = SUM ( expired_stock[units_expired] )
Operational Rescue Ratio = DIVIDE ( [Value Rescued], [Value Rescued]+[Waste Incurred] )

-- run-rate / time intelligence for the business view
Revenue MTD = TOTALMTD ( [Platform Revenue], 'Date'[Date] )
Revenue YTD = TOTALYTD ( [Platform Revenue], 'Date'[Date] )
Rescued YTD = TOTALYTD ( [Value Rescued], 'Date'[Date] )
Revenue 3M Avg =
AVERAGEX ( DATESINPERIOD('Date'[Date], MAX('Date'[Date]), -3, MONTH),
           CALCULATE ( [Platform Revenue] ) )   -- smoothed monthly run-rate
Annualised Revenue Run-Rate = [Revenue 3M Avg] * 12
```

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| Value Rescued | KPI card with sparkline | `[Value Rescued]` (₦) |
| Platform Revenue | KPI card with sparkline + delta | `[Platform Revenue]` (₦), delta `[Revenue MoM %]` |
| Annualised Run-Rate | KPI card | `[Annualised Revenue Run-Rate]` (₦) — the "what does this become at scale" number |
| Waste Incurred | KPI card with delta | `[Waste Incurred]` (₦), delta `[Waste MoM %]` (reverse colours) |
| Operational Rescue Ratio | KPI card | `[Operational Rescue Ratio]` (%) — label "Operational rescue ratio," NOT "waste reduction" |
| Rescued vs Waste by category | Clustered bar | Axis `drugs[category]`, values `[Value Rescued]`, `[Waste Incurred]` |
| Cumulative revenue (run total) | Line | Axis `Date[MonthStart]`, value `[Platform Revenue]` as running total |
| Waste registry | Table | `pharmacies[pharmacy_id]`, `drugs[name]`, `expired_stock[units_expired]`, `expired_stock[value_lost]`, `expired_stock[expiry_date]` |
| Commission note | Text box | "Platform earns only on completed transfers — avg commission `[Avg Commission %]`." |

> **Honesty label (keep this):** Operational Rescue Ratio is a live in-app ratio
> (rescued ÷ rescued+incurred). It is NOT the Chapter 4 evaluation figure (~51% vs the realistic
> baseline) from `evaluate.py` under Monte Carlo. Keep the wording distinct so the two are
> never confused in the viva.

**Management read:** revenue level + MoM + annualised run-rate is the classic exec revenue
triplet; rescued-vs-waste-by-category shows where the model wins and where leakage remains.

---

## PAGE 5 — Business Model & Unit Economics
*"How does this sustain itself, and what does one transfer earn?"* (business-school centrepiece)

### Measures this page needs
```DAX
Revenue Per Transfer = DIVIDE ( [Platform Revenue], [Completed Transfers] )
Value Rescued Per Transfer = DIVIDE ( [Value Rescued], [Completed Transfers] )
Revenue Per Active Pharmacy = DIVIDE ( [Platform Revenue], [Active Pharmacies] )
Adoption Rate =
DIVIDE (
  CALCULATE ( DISTINCTCOUNT ( redistribution_recommendations[source_pharmacy_id] ),
              redistribution_recommendations[status]="ACCEPTED" ),
  [Active Pharmacies] )
Adoption MoM pts =
VAR Cur = [Adoption Rate]
VAR Prev = CALCULATE ( [Adoption Rate], DATEADD('Date'[Date],-1,MONTH) )
RETURN Cur - Prev
```
(reuses `[Platform Revenue]`,`[Revenue MTD]`,`[Revenue YTD]`,`[Annualised Revenue Run-Rate]`,`[Avg Commission %]`)

### Visuals and their fields
| Visual | Type | Fields / measures |
|---|---|---|
| Platform Revenue (total) | KPI card | `[Platform Revenue]` |
| Revenue YTD | KPI card | `[Revenue YTD]` |
| Annualised Run-Rate | KPI card | `[Annualised Revenue Run-Rate]` |
| Revenue per transfer | KPI card | `[Revenue Per Transfer]` (₦) — unit economics |
| Revenue per active pharmacy | KPI card | `[Revenue Per Active Pharmacy]` (₦) — ARPU equivalent |
| Adoption rate | KPI card with delta | `[Adoption Rate]` (%), delta `[Adoption MoM pts]` |
| Revenue by area | Bar | Axis `pharmacies[area]`, value `[Platform Revenue]` |
| Revenue by category | Bar | Axis `drugs[category]`, value `[Platform Revenue]` |
| Revenue trend & run-rate | Line + constant line | Axis `Date[MonthStart]`, value `[Platform Revenue]`, constant line `[Revenue 3M Avg]` |
| Cost-base note | Text box | "Lean cost base: open-source stack + cloud hosting + messaging gateway. A small per-transfer commission funds the platform; profitability is a pilot question." |

**Management read:** this is the unit-economics page — revenue per transfer and per pharmacy
(the ARPU analogue), adoption as the growth lever, and the run-rate as the scale story. It turns
"it reduces waste" into "here is the business."

---

## Build priority
For the thesis: build **Page 1 (Executive Summary) + Page 4 (Impact/Revenue/Waste)** first — they
carry the management story and prove the live data feed. Add Pages 2, 3, 5 as time allows. For the
demo, open on Page 1 (the 10-second board view), then drill into Page 4 and Page 5 for the
business case.

## Format tips
- ₦ cards: currency, thousands separators, 0 decimals. Ratios: %, 1 decimal.
- For "down is good" deltas (Waste MoM %, Value At Risk MoM %): set conditional formatting so
  negative = green, positive = red (reverse of the default).
- Accent colour `#0F6E5C` to match the app brand.
- Sparklines: keep them line type, brand colour, no axis labels — they're for shape, not reading.
- The 3-month-average run-rate smooths the noise of a small early dataset; mention in the demo
  that it's a smoothed projection, not a guarantee — consistent with the project's honesty stance.

## What changed from v3
- Added the full time-intelligence layer back: MoM % deltas on every headline KPI, running
  totals, MTD/YTD, a 3-month-average run-rate, and an annualised run-rate.
- Sparklines specified on the KPI cards (with the how-to in Section 0).
- Page 1 reframed as an **Executive Summary** (board-level 10-second read).
- Page 5 expanded into **Business Model & Unit Economics** (revenue per transfer, revenue per
  pharmacy/ARPU, adoption rate, run-rate) — the management/business angle made explicit.
- Colour-reversal guidance for "down-is-good" metrics so the dashboard reads correctly to execs.
