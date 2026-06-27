# Inter-Pharmacy Drug Redistribution — Build Guide

A working implementation of the framework from your thesis: a calibrated data
generator, three models (expiry-risk classifier, demand forecaster, redistribution
matcher), a FastAPI backend, and a Streamlit pharmacist app — all on PostgreSQL.

You are on **Windows**, comfortable with the command line. Commands below use
PowerShell. Run them from the project root (`pharma_redist`) unless told otherwise.

---

## 0. What you are building (the map)

```
 your cleaned survey  ─►  generator  ─►  PostgreSQL  ◄─►  3 models  ─►  recommendations
 (data/*.xlsx)            (synthetic        (all data)     (1,2,3)        │
                           150-pharmacy                                   ▼
                           network)                          FastAPI  +  Streamlit app
                                                                  │
                                                                  ▼
                                                            evaluation (Monte Carlo)
```

Build order (each step works before the next):
**setup → database → generator → Model 1 → Model 2 → Model 3 → pipeline → app → evaluation.**

---

## 1. One-time setup

### 1a. Install PostgreSQL (local)
1. Download the installer from postgresql.org (the EDB Windows installer).
2. During install, set a password for the `postgres` user — remember it.
3. After install, open **pgAdmin** (or `psql`) and create the database:
   ```sql
   CREATE DATABASE pharma_redist;
   ```
   Or from PowerShell (psql is added to PATH by the installer):
   ```powershell
   psql -U postgres -c "CREATE DATABASE pharma_redist;"
   ```

> Later, for the pilot, swap to a free cloud Postgres (Neon or Supabase). You will
> only change `DATABASE_URL` in `.env` — no code changes.

### 1b. Python environment
```powershell
cd pharma_redist
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
(If activation is blocked: `Set-ExecutionPolicy -Scope Process RemoteSigned` then retry.)

### 1c. Configuration
```powershell
copy .env.example .env
```
Open `.env` and set `DATABASE_URL` to your password, e.g.:
```
DATABASE_URL=postgresql+psycopg2://postgres:YOURPASSWORD@localhost:5432/pharma_redist
```

### 1d. Drop in your cleaned data
Copy these three files (from the cleaning step) into the `data/` folder:
- `survey_clean.xlsx`
- `drugs_long.xlsx`
- `expired_long.xlsx`

### 1e. Test the database connection
```powershell
python -m src.db
# expect:  Database reachable: True
```

---

## 2. Create the database schema
Creates the 7 core tables + coordination tables. Safe to re-run (it drops & recreates).
```powershell
psql -U postgres -d pharma_redist -f db/schema.sql
```
Expect no errors. Verify in psql: `\dt` lists 11 tables.

---

## 3. Generate the calibrated network
Reads your survey, keeps the 39 real pharmacies as anchors, and creates synthetic
ones up to `N_PHARMACIES` (150), with daily sales and inventory batches.
```powershell
python -m src.generator
```
Expect a summary like: `pharmacies 150 | drugs ~40 | batches ~400 | sales_rows ~100k`.
This is the foundation — everything else reads from these tables.

---

## 4. Model 1 — expiry-risk classifier (XGBoost)
Train, then score every current batch into `expiry_risk_scores`.
```powershell
python -m src.model1_expiry --train
python -m src.model1_expiry --score
```
Training prints AUC-ROC, Recall (the primary metric), Precision, Brier score.
Scoring prints tier counts (Low / Medium / High / Critical).

---

## 5. Model 2 — probabilistic demand forecaster
Holt-Winters for regular demand, TSB/Croston for intermittent (slow movers).
Writes q10/q50/q90 over 7/14/30-day horizons into `demand_forecasts`.
```powershell
python -m src.model2_forecast --run
```

---

## 6. Model 3 — redistribution matching
For every High/Critical batch, shortlists nearby pharmacies that need the drug,
confirms they can sell it in time (Model 2 quantile), scores the transfer on the
four weighted factors, and writes matches above the threshold into
`redistribution_recommendations`.
```powershell
python -m src.model3_matching --run
```

> Steps 4–6 in one command (the "nightly run"):
> ```powershell
> python -m src.pipeline
> ```

---

## 7. The app
### 7a. Streamlit pharmacist app (the demo UI)
```powershell
streamlit run app/streamlit_app.py
```
Opens in your browser. Pick a pharmacy in the sidebar, see its at-risk stock and
the recommendations it can accept or decline.

### 7b. FastAPI backend (optional, for integration/automation)
```powershell
uvicorn api.main:app --reload --port 8000
```
Interactive docs: http://127.0.0.1:8000/docs

---

## 8. Evaluation (Objective V)
Monte Carlo simulation; reports waste-reduction vs two baselines with 95% CIs.
```powershell
python -m src.evaluate --runs 200
```

---

## 9. Daily cycle, once it's running
```powershell
python -m src.pipeline          # refresh scores, forecasts, recommendations
streamlit run app/streamlit_app.py
```

---

## Project layout
```
pharma_redist/
  config.py              settings (reads .env)
  requirements.txt
  .env.example           copy to .env
  db/schema.sql          all tables
  data/                  put cleaned survey xlsx here
  models/                trained model saved here
  src/
    db.py                DB connection helper
    generator.py         calibrated hybrid data generator
    features.py          leakage-safe feature engineering (Model 1)
    model1_expiry.py     XGBoost expiry-risk classifier
    model2_forecast.py   Holt-Winters + Croston/TSB forecaster
    model3_matching.py   spatial multi-criteria + transshipment LP
    pipeline.py          nightly orchestration
    evaluate.py          Monte Carlo evaluation
  api/main.py            FastAPI backend
  app/streamlit_app.py   Streamlit pharmacist UI
```

## Mapping to the thesis
| Chapter 3 | Code |
|---|---|
| 3.1.5 Calibrated synthetic generation | `src/generator.py` |
| 3.1.6 Database design | `db/schema.sql` |
| 3.1.7 Feature engineering | `src/features.py` |
| 3.2 Expiry-risk classifier | `src/model1_expiry.py` |
| 3.3.1 Demand forecasting | `src/model2_forecast.py` |
| 3.3.2 Spatial multi-criteria + transshipment | `src/model3_matching.py` |
| 3.4 Platform | `api/main.py`, `app/streamlit_app.py` |
| 3.5 Evaluation | `src/evaluate.py` |

## Troubleshooting
- **`Database reachable: False`** — Postgres service not running, or wrong password
  in `.env`. Check Services → "postgresql" is started.
- **`relation ... does not exist`** — run Step 2 (schema) before the generator.
- **Only one class in labels (Model 1)** — increase `SIM_DAYS` in `.env` and
  regenerate, so more batches reach expiry and create both classes.
- **No recommendations** — make sure Steps 4–6 all ran today (scores/forecasts are
  dated `CURRENT_DATE`); re-run `python -m src.pipeline`.
- **psql not recognised** — add `C:\Program Files\PostgreSQL\16\bin` to PATH, or run
  the SQL from pgAdmin's Query Tool instead.

## Notes on honesty (carry into the thesis)
- This runs on the **calibrated synthetic** network; results are projections, not
  field outcomes. The real survey rows are anchors (hybrid corpus).
- Distance uses **Haversine** here; swap in a maps-API road travel time for the pilot
  (see the note in `src/model3_matching.py`).
- Acceptance in the evaluation is a **survey-anchored assumption**, varied via
  `--acceptance`; it is not a measured rate.
