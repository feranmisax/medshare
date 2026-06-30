# MedShare — Power BI Management Dashboard Specification

The management/oversight layer, sitting on the **same PostgreSQL tables** the app uses.
Streamlit answers *"what do I do now?"*; this dashboard answers *"is the network healthy
and is the intervention working?"*

**Connect:** Power BI Desktop → Get Data → PostgreSQL database → Server `localhost`,
Database `pharma_redist` → **Import** mode (time intelligence and sparklines need Import,
not DirectQuery). Load: `pharmacies`, `drugs`, `inventory_batches`, `sales_daily`,
`expiry_risk_scores`, `demand_forecasts`, `redistribution_recommendations`, `transfers`.

---

## 0. Data model (do this first)

### 0.1 Calculated date columns
`created_at` columns are timestamps; relationships to a Date table need a pure date.
Add these calculated columns (Modeling → New Column):

```DAX
-- on redistribution_recommendations
Created Date = DATE ( YEAR([created_at]), MONTH([created_at]), DAY([created_at]) )

-- on transfers
Created Date = DATE ( YEAR([created_at]), MONTH([created_at]), DAY([created_at]) )
```
`sales_daily[sale_date]` and `expiry_risk_scores[score_date]` are already dates.

### 0.2 Date table
New Table:
```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2025, 1, 1 ), DATE ( 2026, 12, 31 ) ),
    "Year",      YEAR ( [Date] ),
    "MonthNo",   MONTH ( [Date] ),
    "Month",     FORMAT ( [Date], "MMM" ),
    "YearMonth", FORMAT ( [Date], "YYYY-MM" ),
    "Day",       DAY ( [Date] ),
    "Weekday",   FORMAT ( [Date], "ddd" )
)
```
Then: select the table → **Table tools → Mark as date table** → choose `[Date]`.

### 0.3 Relationships
Star around two dimensions (`pharmacies`, `drugs`) plus the `Date` table:

| From (many) | To (one) | Notes |
|---|---|---|
| `inventory_batches[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `inventory_batches[drug_id]` | `drugs[drug_id]` | active |
| `sales_daily[pharmacy_id]` | `pharmacies[pharmacy_id]` | active |
| `sales_daily[drug_id]` | `drugs[drug_id]` | active |
| `expiry_risk_scores[batch_id]` | `inventory_batches[batch_id]` | active |
| `redistribution_recommendations[batch_id]` | `inventory_batches[batch_id]` | active |
| `redistribution_recommendations[source_pharmacy_id]` | `pharmacies[pharmacy_id]` | **active** (source role) |
| `redistribution_recommendations[target_pharmacy_id]` | `pharmacies[pharmacy_id]` | **inactive** (use `USERELATIONSHIP` for target) |
| `transfers[rec_id]` | `redistribution_recommendations[rec_id]` | active |
| `Date[Date]` | `sales_daily[sale_date]` | active |
| `Date[Date]` | `expiry_risk_scores[score_date]` | active |
| `Date[Date]` | `redistribution_recommendations[Created Date]` | active |
| `Date[Date]` | `transfers[Created Date]` | active |

(Each fact gets its own active link to `Date`, which is allowed because they are different tables.)

---

## 1. Measures library

Create a blank table named `_Measures` (New Table → `_Measures = {BLANK()}`) and put all
measures there so they're easy to find.

### 1.1 Network base
```DAX
Total Pharmacies = DISTINCTCOUNT ( pharmacies[pharmacy_id] )

Total Batches = COUNTROWS ( inventory_batches )

Stock Value (₦) =
SUMX ( inventory_batches, inventory_batches[quantity] * inventory_batches[unit_price] )

Willing to Receive % =
DIVIDE (
    CALCULATE ( DISTINCTCOUNT ( pharmacies[pharmacy_id] ), pharmacies[willing_receive] = "Yes" ),
    [Total Pharmacies]
)
```

### 1.2 Expiry risk (uses latest scoring snapshot)
```DAX
Last Score Date =
CALCULATE ( MAX ( expiry_risk_scores[score_date] ), ALL ( expiry_risk_scores[score_date] ) )

Critical Batches =
CALCULATE (
    DISTINCTCOUNT ( expiry_risk_scores[batch_id] ),
    expiry_risk_scores[score_date] = [Last Score Date],
    expiry_risk_scores[risk_tier] = "Critical"
)

High Batches =
CALCULATE (
    DISTINCTCOUNT ( expiry_risk_scores[batch_id] ),
    expiry_risk_scores[score_date] = [Last Score Date],
    expiry_risk_scores[risk_tier] = "High"
)

At-Risk Batches =
CALCULATE (
    DISTINCTCOUNT ( expiry_risk_scores[batch_id] ),
    expiry_risk_scores[score_date] = [Last Score Date],
    expiry_risk_scores[risk_tier] IN { "High", "Critical" }
)

At-Risk Value (₦) =
SUMX (
    FILTER (
        expiry_risk_scores,
        expiry_risk_scores[score_date] = [Last Score Date]
            && expiry_risk_scores[risk_tier] IN { "High", "Critical" }
    ),
    RELATED ( inventory_batches[quantity] ) * RELATED ( inventory_batches[unit_price] )
)

Avg Days to Expiry (at risk) =
AVERAGEX (
    FILTER (
        expiry_risk_scores,
        expiry_risk_scores[score_date] = [Last Score Date]
            && expiry_risk_scores[risk_tier] IN { "High", "Critical" }
    ),
    DATEDIFF ( TODAY (), RELATED ( inventory_batches[expiry_date] ), DAY )
)

Expiring within 30 days =
CALCULATE (
    [Total Batches],
    FILTER ( inventory_batches, DATEDIFF ( TODAY (), inventory_batches[expiry_date], DAY ) <= 30 )
)
```

### 1.3 Redistribution activity
```DAX
Recommendations Total    = COUNTROWS ( redistribution_recommendations )
Recommendations Open     = CALCULATE ( [Recommendations Total], redistribution_recommendations[status] = "RECOMMENDED" )
Recommendations Accepted = CALCULATE ( [Recommendations Total], redistribution_recommendations[status] = "ACCEPTED" )
Recommendations Declined = CALCULATE ( [Recommendations Total], redistribution_recommendations[status] = "DECLINED" )

Acceptance Rate =
DIVIDE ( [Recommendations Accepted], [Recommendations Accepted] + [Recommendations Declined] )

Avg Match Score        = AVERAGE ( redistribution_recommendations[match_score] )
Avg Transfer Distance  = AVERAGE ( redistribution_recommendations[distance_km] )
```

### 1.4 Transfers & impact
```DAX
Transfers Accepted =
CALCULATE ( COUNTROWS ( transfers ), transfers[status] IN { "ACCEPTED", "IN_TRANSIT", "COMPLETED" } )

Value Rescued (₦) =
SUMX (
    FILTER ( transfers, transfers[status] IN { "ACCEPTED", "IN_TRANSIT", "COMPLETED" } ),
    transfers[agreed_price] * transfers[agreed_quantity]
)

-- Dashboard approximation only. The authoritative waste-reduction % is the
-- Monte Carlo result from evaluate.py (vs B0/B1). Cite that in the thesis.
Waste-Reduction (approx %) =
DIVIDE ( [Value Rescued (₦)], [At-Risk Value (₦)] + [Value Rescued (₦)] )

Pharmacies Participating =
CALCULATE (
    DISTINCTCOUNT ( pharmacies[pharmacy_id] ),
    FILTER (
        pharmacies,
        pharmacies[pharmacy_id] IN VALUES ( redistribution_recommendations[source_pharmacy_id] )
        || pharmacies[pharmacy_id] IN VALUES ( redistribution_recommendations[target_pharmacy_id] )
    )
)
```

### 1.5 Demand
```DAX
Units Sold = SUM ( sales_daily[units_sold] )
```

---

## 2. Time-intelligence measures (for trends, MoM, sparklines)

```DAX
Units Sold MTD = TOTALMTD ( [Units Sold], 'Date'[Date] )
Units Sold YTD = TOTALYTD ( [Units Sold], 'Date'[Date] )

Units Sold MoM % =
VAR Cur  = [Units Sold]
VAR Prev = CALCULATE ( [Units Sold], DATEADD ( 'Date'[Date], -1, MONTH ) )
RETURN DIVIDE ( Cur - Prev, Prev )

Units Sold (rolling 30d) =
CALCULATE ( [Units Sold], DATESINPERIOD ( 'Date'[Date], MAX ( 'Date'[Date] ), -30, DAY ) )

-- daily activity (these power the sparklines)
Recs Created (daily)  = [Recommendations Total]      -- in a Date[Date] axis context
Transfers (daily)     = [Transfers Accepted]         -- in a Date[Date] axis context
Value Rescued (daily) = [Value Rescued (₦)]          -- in a Date[Date] axis context

Cumulative Value Rescued (₦) =
CALCULATE (
    [Value Rescued (₦)],
    FILTER ( ALLSELECTED ( 'Date'[Date] ), 'Date'[Date] <= MAX ( 'Date'[Date] ) )
)

Recs Created MoM % =
VAR Cur  = [Recommendations Total]
VAR Prev = CALCULATE ( [Recommendations Total], DATEADD ( 'Date'[Date], -1, MONTH ) )
RETURN DIVIDE ( Cur - Prev, Prev )
```

---

## 3. Sparklines on the KPI cards

Native sparklines in Power BI live inside a **table/matrix**, so build each KPI strip as a
one-row **Matrix** styled to look like cards, then add a sparkline to the measure cells.

Steps per KPI strip:
1. Insert a **Matrix**. Put nothing in Rows (or a single constant), put the KPI **measures**
   in Values (e.g. `Units Sold`, `Recommendations Total`, `Value Rescued (₦)`).
2. Click the measure in Values → **Add a sparkline**.
3. In the sparkline dialog: **Y-axis** = the trend measure (e.g. `Value Rescued (daily)`),
   **X-axis** = `'Date'[Date]`, summarize = Sum, line type = Line (or Column).
4. Format → Style → remove gridlines, set row/column headers off, enlarge the value font so
   it reads like a card. Set the sparkline line colour to your brand green `#0F6E5C`.

Alternative if you prefer separate visuals: use the built-in **KPI** visual
(Value = the measure, Trend axis = `'Date'[Date]`), which draws its own trend line behind the
number. Sparklines-in-matrix gives the tighter "card with mini-trend" look you asked for.

---

## 4. Pages

Common to all pages — add these **slicers** (sync across pages via View → Sync slicers):
`Date[Date]` (range), `pharmacies[area]`, `drugs[category]`, `pharmacies[pharmacy_type]`.
Add a text box bottom-right: `="Last refreshed " & FORMAT(NOW(),"dd mmm yyyy, HH:MM")`.
Keep tier colours consistent everywhere: Critical `#B4231C`, High `#C8861A`,
Medium `#2C7A6B`, Low `#7A8A84`, brand `#0F6E5C`.

---

### PAGE 1 — Network Overview
*Audience: executives. Question: is the network healthy?*

**KPI cards (matrix strip with sparklines):**
| KPI | Measure | Sparkline trend |
|---|---|---|
| Pharmacies | `Total Pharmacies` | — |
| Batches tracked | `Total Batches` | — |
| Stock value | `Stock Value (₦)` | `Units Sold (rolling 30d)` (proxy for turnover) |
| Value at risk | `At-Risk Value (₦)` | `Value Rescued (daily)` |
| Expiring ≤30 days | `Expiring within 30 days` | — |
| Willing to receive | `Willing to Receive %` | — |

**Visuals:**
| Visual type | Fields | Purpose |
|---|---|---|
| **Map** (Azure/Bing Map) | Latitude `pharmacies[latitude]`, Longitude `pharmacies[longitude]`, Bubble size = `At-Risk Value (₦)`, Legend = `pharmacies[pharmacy_type]` | where the opportunity is |
| **Clustered bar** | Axis `pharmacies[pharmacy_type]`, Value `Total Pharmacies` | network composition |
| **Donut** | Legend `drugs[category]`, Value `Stock Value (₦)` | value by category |
| **Table** | `pharmacies[pharmacy_id]`, `pharmacies[area]`, `At-Risk Value (₦)` (sort desc, Top 5 via filter) | who needs attention |

---

### PAGE 2 — Expiry Risk (Model 1)
*Audience: operations/clinical lead. Question: what is predicted to be wasted, and where?*

**KPI cards:**
| KPI | Measure | Sparkline trend |
|---|---|---|
| Critical batches | `Critical Batches` | — |
| High batches | `High Batches` | — |
| Value flagged critical | filter `At-Risk Value (₦)` to Critical (visual-level filter) | — |
| Avg days to expiry (at risk) | `Avg Days to Expiry (at risk)` | — |

**Visuals:**
| Visual type | Fields | Purpose |
|---|---|---|
| **Stacked column** | Axis `drugs[category]`, Legend `expiry_risk_scores[risk_tier]`, Value `At-Risk Batches` | which categories are the problem |
| **Histogram / column** | Axis = days-to-expiry buckets (new column `DATEDIFF(TODAY(),expiry_date,DAY)` binned), Value `Total Batches`, Legend tier | how soon, how risky |
| **Bar** | Axis `pharmacies[area]`, Value `At-Risk Value (₦)` | risk by location |
| **Matrix table** | Rows `drugs[name]`, `pharmacies[pharmacy_id]`; Values `inventory_batches[quantity]`, `At-Risk Value (₦)`, `Avg Days to Expiry (at risk)`, `expiry_risk_scores[risk_probability]` | the watch-list |

---

### PAGE 3 — Redistribution Activity (Model 3)
*Audience: programme manager. Question: is stock actually moving?*

**KPI cards:**
| KPI | Measure | Sparkline trend |
|---|---|---|
| Recommendations generated | `Recommendations Total` | `Recs Created (daily)` |
| Accepted | `Recommendations Accepted` | `Transfers (daily)` |
| Acceptance rate | `Acceptance Rate` | — |
| Avg match score | `Avg Match Score` | — |
| Avg distance (km) | `Avg Transfer Distance` | — |

**Visuals:**
| Visual type | Fields | Purpose |
|---|---|---|
| **Funnel** | Categories = status stages, Value `Recommendations Total` (and `Transfers Accepted`) | RECOMMENDED → ACCEPTED → COMPLETED drop-off |
| **Clustered bar** | Axis `redistribution_recommendations[status]`, Value `Recommendations Total` | pipeline by status |
| **Scatter** | X `redistribution_recommendations[distance_km]`, Y `redistribution_recommendations[match_score]`, size `redistribution_recommendations[quantity]` | engine favours close, high-quality matches |
| **Map with lines** (or table) | source lat/long → target lat/long for accepted recs | redistribution happening across the city |
| **Table** | source, target, `drugs[name]`, `quantity`, `suggested_price`, `match_score`, `status` | recent activity log |

---

### PAGE 4 — Impact & Waste Prevented
*Audience: executive sponsor / investor. Question: is it working, in money?*

**KPI cards:**
| KPI | Measure | Sparkline trend |
|---|---|---|
| Value rescued | `Value Rescued (₦)` | `Value Rescued (daily)` |
| Waste-reduction (approx) | `Waste-Reduction (approx %)` | — |
| Transfers completed | `Transfers Accepted` | `Transfers (daily)` |
| Pharmacies participating | `Pharmacies Participating` | — |

**Visuals:**
| Visual type | Fields | Purpose |
|---|---|---|
| **Gauge** | Value `Waste-Reduction (approx %)`, Target = your Monte Carlo figure (e.g. 0.46) | progress to benchmark |
| **Clustered column** | Axis = baseline label, Values `At-Risk Value (₦)` (no-redistribution) vs `At-Risk Value (₦)` − `Value Rescued (₦)` (with) | waste avoided |
| **Area / line** | Axis `Date[Date]`, Value `Cumulative Value Rescued (₦)` | money saved over time |
| **Bar** | Axis `drugs[category]` (or `pharmacies[area]`), Value `Value Rescued (₦)` | where benefit concentrates |

> **Honesty note for the thesis:** the dashboard's `Waste-Reduction (approx %)` is a live
> snapshot ratio for monitoring; the *authoritative* waste-reduction figures (54.2% vs B0;
> 46.3% vs B1, with sensitivity 32–62%) come from the Monte Carlo evaluation in `evaluate.py`
> and are what you report in Chapter 4. Use the gauge target to tie the two together.

---

## 5. Scope guidance
For the thesis, **Page 1 + Page 4** alone prove the management layer exists and is fed by the
same database — build those first. Add Pages 2 and 3 if time allows. For a pilot/business, all
four are the right design.
