# MedShare — Inter-Pharmacy Drug Redistribution Framework

An integrated decision-support framework that helps community and hospital
pharmacies redistribute surplus, near-expiry medicines to other pharmacies that
need them — before the stock expires and the value is lost.

The framework combines three models behind a single platform:

1. **Expiry-risk classifier** — predicts which stock batches are likely to expire unsold.
2. **Demand forecaster** — estimates near-term demand per pharmacy and drug, with uncertainty.
3. **Redistribution matcher** — pairs at-risk surplus with pharmacies that can sell it in time.

It is delivered as a PostgreSQL database, a FastAPI backend, and a Streamlit
pharmacist application, evaluated by Monte Carlo simulation. This repository is the
reference implementation accompanying the MSc thesis.

> **Scope.** The system is evaluated on a **calibrated synthetic network** anchored to
> a 39-pharmacy survey. Reported impact figures are **simulation-based projections**,
> not measured field outcomes. See [Data & honesty](#data--honesty).

---

## Architecture

```
 Survey (39 pharmacies, real)          +------------------------------+
   data/*.xlsx  --> generator -->      |      PostgreSQL database       |
                    (hybrid 150-        |  stock . sales . scores .      |
                     pharmacy network)  |  forecasts . recommendations . |
                                        |  transfers . requests . waste  |
                                        +--------------+-----------------+
        +------------------------------+              |
        |  Models (nightly pipeline)    |<-------------+
        |  1 expiry risk (XGBoost)      |              |
        |  2 demand forecast (HW / TSB) |--------------+
        |  3 matching (heuristic + LP)  |              |
        +------------------------------+               |
        +------------------------------+               |
        |  FastAPI backend . Streamlit  |<-------------+
        |  app (pharmacist portal)      |--------------+  (log stock, accept/decline)
        +------------------------------+
        +------------------------------+
        |  Monte Carlo evaluation       |  waste-reduction curve, break-even
        +------------------------------+
```

Three layers: a **storage layer** (a single PostgreSQL database, the source of truth
for every component), a **processing layer** (the data pipeline, the three models,
and the FastAPI backend), and a **user layer** (the Streamlit pharmacist app and a
Power BI dashboard that reads the same database).

---

## The three models

| Model | Method | Why this method | Output table |
|---|---|---|---|
| **1 — Expiry risk** | XGBoost (probability-calibrated), benchmarked against Logistic Regression and Random Forest under an identical protocol | Interpretable, calibrated probabilities and feature importances the matcher relies on; retained as the documented primary when within tolerance of the best AUC | `expiry_risk_scores` |
| **2 — Demand forecast** | Holt-Winters for regular demand; TSB (Croston-family) for intermittent slow movers, routed automatically | Two-track routing handles both fast- and slow-moving stock; produces q10/q50/q90 quantiles, not just a point estimate | `demand_forecasts` |
| **3 — Redistribution matching** | Demand-aware coordinated heuristic (urgency-ordered, shared-demand), benchmarked against a transshipment LP optimum | Transparent and real-time on modest hardware while capturing most of the achievable value; the LP quantifies the gap | `redistribution_recommendations` |

**Model 1** learns from a leakage-safe, realised-outcome label: each batch's outcome
is projected forward under simulated demand (calibrated to survey dispersion), so the
label is not an algebraic function of the features. Performance is reported against an
**oracle Bayes-optimal ceiling** to show the model recovers nearly all attainable
signal rather than against a misleading 1.0.

**Model 3** scores each candidate transfer on four weighted factors — source urgency,
target need, geographic proximity, and value (weights 0.35 / 0.35 / 0.20 / 0.10) —
keeping matches above a 0.65 threshold within a 20 km radius (K=10 nearest
candidates). Distance uses the Haversine formula; a maps-API road-travel-time upgrade
is noted for the pilot.

---

## Repository layout

```
pharma_redist/
  config.py                 settings, read from .env (network size, thresholds, sweeps)
  requirements.txt
  .env.example              template - copy to .env and set DATABASE_URL
  db/
    schema.sql              core tables
    migrate_marketplace.sql stock_requests, commission columns
    migrate_expiry.sql      expired_stock registry, is_expired flag
  data/                     cleaned survey inputs (survey_clean, drugs_long, expired_long)
  models/                   trained Model 1 artifact (regenerated on --train)
  src/
    db.py                   single SQLAlchemy engine, reused everywhere
    generator.py            calibrated hybrid data generator (real anchors + synthetic)
    seasonal.py             shared category x month seasonal index (generator + features)
    nafdac.py               optional NAFDAC catalogue validation (no-op if absent)
    features.py             leakage-safe, survey-anchored feature + label engineering
    model1_expiry.py        expiry-risk classifier + benchmarks + oracle ceiling
    model2_forecast.py      demand forecaster (+ --backtest accuracy)
    model3_matching.py      redistribution matcher (+ --gap optimality)
    requests_match.py       pull-side matching for posted stock requests
    pipeline.py             nightly orchestration of the models
    evaluate.py             Monte Carlo evaluation (waste-reduction curve)
    expiry.py               sweep newly-expired stock into the waste registry
    auth.py                 login / pharmacy identity
    emailer.py              notification emails
    dashboard.py            in-app dashboard helpers
  api/main.py               FastAPI backend
  app/streamlit_app.py      Streamlit pharmacist portal
  chapter4_stats.py         one-shot operational snapshot for the results chapter
```

---

## The database

A single PostgreSQL database is the source of truth for every component. Core tables
include `pharmacies`, `drugs`, `inventory_batches`, `sales_daily`,
`expiry_risk_scores`, `demand_forecasts`, `redistribution_recommendations`,
`transfers`, `stock_requests`, `expired_stock`, and supporting tables for users and
notifications. The schema plus migrations define roughly a dozen interconnected
tables with foreign-key constraints.

Pharmacist-logged stock is written with `is_synthetic = FALSE`, keeping real
user-entered inventory distinguishable from the generated network throughout.

---

## Configuration

All settings live in `config.py` and are overridable via `.env`. Key ones:

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | - | PostgreSQL connection (local or cloud; the only thing to change to move to Neon) |
| `N_PHARMACIES` | 150 | Total network size (39 real anchors + synthetic) |
| `SIM_DAYS` | 365 | Length of the simulated sales history |
| `MATCH_THRESHOLD` | 0.65 | Minimum match score to recommend a transfer |
| `MAX_DISTANCE_KM` | 20 | Maximum transfer radius |
| `K_NEAREST` | 10 | Candidate targets considered per at-risk batch |
| `SERVICE_LEVEL` | 0.8 | Forecast quantile used to confirm the receiver can sell in time |
| `ACCEPTANCE_SWEEP` / `B1_CLEAR_SWEEP` | - | Ranges swept in the evaluation |

Moving from local Postgres to a cloud database (Neon, Supabase) requires **only**
changing `DATABASE_URL` - no code changes.

---

## Command reference

Run from the project root with the virtual environment active. Each command reads and
writes the database at `DATABASE_URL`.

| Command | Purpose |
|---|---|
| `python -m src.db` | Check database connectivity |
| `python -m src.generator` | Build the calibrated 150-pharmacy network |
| `python -m src.model1_expiry --train` | Train Model 1; prints the LR / RF / XGBoost / oracle benchmark |
| `python -m src.model1_expiry --score` | Score every live batch into risk tiers |
| `python -m src.model2_forecast --run` | Write demand forecasts |
| `python -m src.model2_forecast --backtest` | Report forecast accuracy (MASE, WAPE, pinball, coverage) |
| `python -m src.model3_matching --run` | Generate redistribution recommendations |
| `python -m src.model3_matching --gap` | Report heuristic-vs-LP optimality gap |
| `python -m src.pipeline` | Run the full nightly cycle (expiry sweep -> score -> forecast -> match -> notify) |
| `python -m src.evaluate --runs 200 --curve` | Monte Carlo evaluation: waste-reduction curve, break-even, sensitivity |
| `python chapter4_stats.py` | Print the operational snapshot for the results chapter |
| `streamlit run app/streamlit_app.py` | Launch the pharmacist app |
| `uvicorn api.main:app --reload --port 8000` | Launch the FastAPI backend (docs at /docs) |

The Streamlit app lets a pharmacy **log newly received stock**, view its at-risk
batches, offer surplus, post and fulfil requests, and accept or decline transfers -
all writing live to the database.

For first-time setup (installing PostgreSQL, creating the environment, loading the
schema and data), see **SETUP.md**.

---

## Data & honesty

- The network is a **hybrid corpus**: 39 real surveyed pharmacies as anchors, plus
  synthetic pharmacies, sales, and inventory generated to match the survey's observed
  demand levels, expiry rates, and willingness parameters.
- The survey collected average weekly demand, expiry incidence, and willingness - not
  daily sales or batch-level inventory (most pharmacies keep no digital daily records).
  The daily series and current stock are therefore **simulated, calibrated to survey
  evidence**, not collected field data.
- Model-label uncertainty parameters are **anchored to measured survey dispersion**,
  so results are discovered from evidence-based assumptions rather than tuned.
- Evaluation acceptance is a **survey-anchored assumption**, reported across a curve
  (with a break-even point), not as a measured adoption rate.
- **In-app transfer activity demonstrates that the platform functions** (a functional
  demonstration); **quantified impact comes only from the Monte Carlo evaluation.**
  The two are kept distinct throughout.

Reported impact figures are projections under empirically-informed conditions and are
not a substitute for large-scale real-world validation, which is the framework's
intended next step.

---

## Thesis mapping

| Chapter 3 section | Implementation |
|---|---|
| Calibrated synthetic generation | `src/generator.py`, `src/seasonal.py`, `src/nafdac.py` |
| Data management | `db/schema.sql` and migrations |
| Feature engineering & labelling | `src/features.py` |
| Expiry-risk classifier | `src/model1_expiry.py` |
| Demand forecasting | `src/model2_forecast.py` |
| Redistribution matching | `src/model3_matching.py`, `src/requests_match.py` |
| Platform | `api/main.py`, `app/streamlit_app.py` |
| Evaluation | `src/evaluate.py` |