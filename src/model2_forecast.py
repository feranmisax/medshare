"""
Model 2 — probabilistic demand forecaster.

For each (pharmacy, drug) daily series:
  - regular demand  -> Holt-Winters / exponential smoothing
  - intermittent    -> TSB (primary) with Croston as fallback
Outputs predictive quantiles (q10/q50/q90) over 7/14/30-day horizons into
demand_forecasts. The quantiles feed the chance constraint in Model 3 and the
"can the receiver sell it in time?" check.

Run:  python -m src.model2_forecast --run
"""
import sys, argparse
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

import config
from src import db

HORIZONS = [7, 14, 30]


def tsb(series, alpha=0.1, beta=0.1):
    """Teunter-Syntetos-Babai intermittent forecast -> per-period mean demand."""
    y = np.asarray(series, dtype=float)
    n = len(y)
    if n == 0:
        return 0.0
    p = 1.0 if y[0] > 0 else 0.0           # demand probability
    z = y[y > 0].mean() if (y > 0).any() else 0.0   # demand size when it occurs
    for t in range(n):
        occurred = 1.0 if y[t] > 0 else 0.0
        p = p + beta * (occurred - p)
        if occurred:
            z = z + alpha * (y[t] - z)
    return max(p * z, 0.0)


def croston(series, alpha=0.1):
    y = np.asarray(series, dtype=float)
    if (y > 0).sum() == 0:
        return 0.0
    z = y[y > 0][0]; x = 1.0; q = 1
    for t in range(1, len(y)):
        if y[t] > 0:
            z = z + alpha * (y[t] - z)
            x = x + alpha * (q - x)
            q = 1
        else:
            q += 1
    return max(z / x, 0.0) if x > 0 else 0.0


def _is_intermittent(y):
    nz = (np.asarray(y) > 0)
    if nz.sum() < 2:
        return True
    adi = len(y) / nz.sum()                 # average inter-demand interval
    return adi >= 1.32


def forecast_series(y):
    """Return (per_day_mean, per_day_std, method)."""
    y = np.asarray(y, dtype=float)
    if _is_intermittent(y):
        mu = tsb(y)
        method = "TSB"
        resid = y - y[y > 0].mean() if (y > 0).any() else y
        sd = float(np.std(resid)) if len(resid) else max(mu, 0.5)
        return mu, max(sd, 0.5), method
    # regular demand: Holt-Winters (additive), fall back to smoothing if it fails
    try:
        m = ExponentialSmoothing(np.clip(y, 0.01, None), trend="add",
                                 seasonal=None, initialization_method="estimated")
        fit = m.fit(optimized=True)
        mu = float(np.mean(fit.forecast(7)))
        sd = float(np.std(fit.resid)) if hasattr(fit, "resid") else float(np.std(y))
        return max(mu, 0.0), max(sd, 0.5), "HoltWinters"
    except Exception:
        return float(np.mean(y)), max(float(np.std(y)), 0.5), "ExpSmoothing"


def run():
    series = db.read_sql("""
        SELECT pharmacy_id, drug_id, sale_date, units_sold
        FROM sales_daily ORDER BY pharmacy_id, drug_id, sale_date
    """)
    if series.empty:
        print("No sales data. Run the generator first.")
        return
    out_rows = []
    today = pd.Timestamp.today().normalize().date()
    for (pid, did), g in series.groupby(["pharmacy_id","drug_id"]):
        y = g["units_sold"].values
        mu, sd, method = forecast_series(y)
        for h in HORIZONS:
            mean_h = mu * h
            sd_h = sd * np.sqrt(h)
            out_rows.append(dict(
                pharmacy_id=pid, drug_id=int(did), forecast_date=today, horizon_days=h,
                q10=round(max(mean_h - 1.2816 * sd_h, 0.0), 2),
                q50=round(max(mean_h, 0.0), 2),
                q90=round(max(mean_h + 1.2816 * sd_h, 0.0), 2),
                method=method,
            ))
    out = pd.DataFrame(out_rows)
    db.run_sql("DELETE FROM demand_forecasts WHERE forecast_date = CURRENT_DATE")
    db.write_df(out, "demand_forecasts")
    print(f"Wrote {len(out)} forecasts for {series.groupby(['pharmacy_id','drug_id']).ngroups} series.")
    print("Methods used:", out["method"].value_counts().to_dict())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.run: run()
    else: print("Use --run")
