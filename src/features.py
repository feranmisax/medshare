"""
Feature engineering for the expiry-risk classifier (Model 1).

The nine features (Chapter 3, Table 3.5):
  stock_level, sales_rate, days_to_expiry, stock_to_sales_ratio,
  inventory_weeks_remaining, drug_category, pharmacy_type,
  historical_expiry_rate, seasonal_index

LEAKAGE-SAFE, REALISED-OUTCOME LABEL (Chapter 3, §3.2.2)
-------------------------------------------------------
The label is the REALISED outcome of each batch under simulated demand, not a
deterministic threshold on the features. Because real drug shelf lives are long
(1-4 years) while the observation window is short, most batches do not expire
inside the observed window; we therefore resolve each batch's outcome by
PROJECTING its demand forward from a decision date to its own expiry date, using
the SAME stochastic demand mechanism the generator uses (a rate estimated from
that pharmacy-drug's observed sales, modulated by the shared seasonal index, drawn
as a Poisson process). A batch is labelled `expired_unsold = 1` if projected
cumulative sales over its remaining shelf life fall short of its quantity.

Features are measured AS OF the decision date; the outcome is resolved only from
the period AFTER that date, up to expiry — so there is no leakage. Because demand
is stochastic (day-to-day noise, intermittency, seasonality), the label is not an
algebraic re-encoding of the features: the model must learn the probabilistic
relationship between decision-time features and an uncertain future outcome.

Run (for a quick look):  python -m src.features
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import config
from src import db
from src.seasonal import seasonal_index

# reproducible label generation (independent of any live RNG state)
_LABEL_RNG = np.random.default_rng(config.RANDOM_SEED + 777)

# Decision point: features are snapshotted when a batch enters its final
# `DECISION_HORIZON_DAYS` of shelf life (or at its received date, whichever is
# later), and the realised outcome is projected forward from there to expiry.
# Using the batch's ACTUAL remaining life (not a fixed lead) means days_to_expiry
# varies across batches and does not near-determine the outcome.
DECISION_HORIZON_DAYS = 90         # look-ahead horizon at the decision point

# Demand-process parameters matched to the generator so the projected outcome is
# realistically UNCERTAIN relative to the decision-time features. The two
# uncertainty parameters below are ANCHORED TO SURVEY EVIDENCE (Chapter 3), not
# chosen to hit a target metric:
GAMMA_DISPERSION = 4.0             # gamma-Poisson (negative-binomial) dispersion (generator r_disp)

# DEMAND_SHOCK_SD — SD of the per-batch multiplicative demand shock (log scale),
# representing temporal demand variation the decision-time snapshot cannot see.
# ANCHOR: the survey's within-drug cross-pharmacy dispersion of weekly demand has
# SD(log) = 1.38. Within-pharmacy TEMPORAL variation is a fraction of that
# cross-sectional spread, so the shock is set conservatively at ~0.35x that bound.
# This value is therefore justified by, and bounded by, observed survey dispersion
# rather than selected for its effect on model accuracy.
_SURVEY_LOG_DEMAND_SD = 1.38       # measured from data/drugs_long.xlsx (within-drug)
DEMAND_SHOCK_SD = round(0.35 * _SURVEY_LOG_DEMAND_SD, 2)   # ~0.48

# DEMAND_CAPTURE — share of series demand a single batch can realistically capture,
# since multiple batches / existing shelf stock of the same drug compete for the
# same buyers (a batch is not the sole supply). ANCHOR: the survey shows a median
# of ~1-2 batches/SKU stocked concurrently plus baseline shelf stock, so a given
# batch captures roughly two-thirds of its series' demand over its window.
DEMAND_CAPTURE = 0.65
# Category intermittency (share of zero-demand days), mirrors the generator.
_EXPIRY_PROP = {"Antibiotics":0.9,"Antimalarials":0.8,"Analgesics":0.5,"Antihypertensives":1.1,
                "Antidiabetics":1.2,"Antacids/GI":0.9,"Vitamins/Supplements":1.0,"Cough/Cold":0.7}
def _p_zero(cat):
    return float(np.clip(0.05 + 0.25 * (_EXPIRY_PROP.get(cat, 1.0) - 0.5), 0.0, 0.6))


def _recent_rate(as_of: pd.Timestamp) -> pd.DataFrame:
    """Mean daily units sold per (pharmacy, drug) over the 28 days BEFORE as_of."""
    return db.read_sql("""
        SELECT pharmacy_id, drug_id, AVG(units_sold) AS daily_rate
        FROM sales_daily
        WHERE sale_date < :as_of AND sale_date >= :start
        GROUP BY pharmacy_id, drug_id
    """, {"as_of": as_of.date(), "start": (as_of - pd.Timedelta(days=28)).date()})


def _all_rates() -> dict:
    """Mean daily sales rate per (pharmacy, drug) over the ENTIRE observed window.
    Used as the forward-projection rate for labelling (a stable estimate of the
    generator's underlying daily_mu for that series)."""
    r = db.read_sql("""
        SELECT pharmacy_id, drug_id, AVG(units_sold) AS daily_rate
        FROM sales_daily GROUP BY pharmacy_id, drug_id
    """)
    return {(row.pharmacy_id, int(row.drug_id)): float(row.daily_rate) for row in r.itertuples()}


def _resolve_expired_unsold(as_of_cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """Resolve each batch's realised outcome by FORWARD-PROJECTING demand from a
    decision point to expiry, under REALISTIC uncertainty.

    The projection deliberately depends on factors the decision-time features do
    NOT fully reveal, so the outcome is genuinely uncertain (not an algebraic
    function of stock and rate):
      * the batch's ACTUAL remaining life (up to DECISION_HORIZON_DAYS), so the
        accumulation window varies batch to batch;
      * gamma-Poisson (negative-binomial) demand with the generator's dispersion;
      * a per-batch multiplicative demand SHOCK (unobserved local conditions);
      * category intermittency (zero-demand days);
      * the seasonal window the remaining life happens to fall in.

    decision_date = max(received_date, expiry_date - DECISION_HORIZON_DAYS)
    expired_unsold = 1 if projected cumulative sales (decision..expiry) < quantity.

    If as_of_cutoff is given, only batches expiring before it are resolved.

    Returns one row per resolved batch:
        batch_id, pharmacy_id, drug_id, category, quantity,
        decision_date, days_to_expiry_at_decision, expired_unsold (0/1)
    """
    batches = db.read_sql("""
        SELECT b.batch_id, b.pharmacy_id, b.drug_id, b.quantity,
               b.received_date, b.expiry_date, d.category
        FROM inventory_batches b
        JOIN drugs d ON d.drug_id = b.drug_id
    """)
    if batches.empty:
        return batches.assign(expired_unsold=[])
    batches["received_date"] = pd.to_datetime(batches["received_date"])
    batches["expiry_date"] = pd.to_datetime(batches["expiry_date"])

    rates = _all_rates()
    out = []

    for (pid, did), grp in batches.groupby(["pharmacy_id", "drug_id"]):
        base_rate = max(rates.get((pid, did), 0.05), 1e-3)
        p0 = None  # set per-category below
        grp = grp.sort_values("expiry_date")
        carry_surplus = 0.0   # demand that earlier-expiry batches did not need
        for row in grp.itertuples():
            if as_of_cutoff is not None and not (row.expiry_date < as_of_cutoff):
                continue
            expiry = row.expiry_date
            decision = max(row.received_date, expiry - pd.Timedelta(days=DECISION_HORIZON_DAYS))
            remaining_days = max((expiry - decision).days, 1)
            days = pd.date_range(decision + pd.Timedelta(days=1), expiry, freq="D")

            p0 = _p_zero(row.category)
            # per-batch demand shock: unobserved conditions scale the whole window
            shock = float(np.exp(_LABEL_RNG.normal(-0.5 * DEMAND_SHOCK_SD**2, DEMAND_SHOCK_SD)))

            projected = 0.0
            for d in days:
                if _LABEL_RNG.random() < p0:          # intermittent zero-demand day
                    continue
                lam = (base_rate * shock * seasonal_index(row.category, d)
                       * _LABEL_RNG.gamma(GAMMA_DISPERSION, 1.0 / GAMMA_DISPERSION))
                projected += _LABEL_RNG.poisson(max(lam, 1e-3))

            projected *= DEMAND_CAPTURE
            allocatable = projected + carry_surplus
            qty = float(row.quantity)
            expired_unsold = 1 if allocatable < qty else 0
            carry_surplus = max(allocatable - qty, 0.0)   # leftover demand helps later batches
            out.append(dict(
                batch_id=row.batch_id, pharmacy_id=pid, drug_id=did,
                category=row.category, quantity=qty,
                decision_date=decision,
                days_to_expiry_at_decision=remaining_days,
                expired_unsold=expired_unsold,
            ))

    return pd.DataFrame(out)


def _historical_expiry_rate_from(resolved: pd.DataFrame) -> pd.DataFrame:
    """Category-level share of resolved batches that lapsed unsold."""
    if resolved.empty:
        return pd.DataFrame(columns=["category", "hist_expiry_rate"])
    return (resolved.groupby("category")["expired_unsold"]
            .mean().reset_index().rename(columns={"expired_unsold": "hist_expiry_rate"}))


def build_feature_table(as_of: pd.Timestamp | None = None,
                        for_training: bool = True) -> pd.DataFrame:
    """Build the feature table.

    for_training=True : one row per RESOLVED batch, features measured at that
                        batch's own decision_date, with the realised label.
    for_training=False: one row per CURRENTLY-LIVE batch, features measured as of
                        `as_of` (today), for scoring — no label.
    """
    as_of = pd.Timestamp(as_of or pd.Timestamp.today().normalize())

    if for_training:
        resolved = _resolve_expired_unsold(as_of_cutoff=None)
        if resolved.empty:
            return pd.DataFrame()

        # per-category historical rate (computed on the resolved set, past-only in
        # spirit: it is the network's overall lapse propensity by category)
        hist = _historical_expiry_rate_from(resolved)
        hist_lookup = hist.set_index("category")["hist_expiry_rate"].to_dict()

        # pull batch context + a decision-date sales rate for each resolved batch
        meta = db.read_sql("""
            SELECT b.batch_id, b.pharmacy_id, b.drug_id, b.quantity, b.unit_price,
                   p.pharmacy_type
            FROM inventory_batches b
            JOIN pharmacies p ON p.pharmacy_id = b.pharmacy_id
        """)
        rates = _all_rates()

        rows = []
        for r in resolved.itertuples():
            m = meta[meta["batch_id"] == r.batch_id]
            if m.empty:
                continue
            m = m.iloc[0]
            rate = rates.get((r.pharmacy_id, int(r.drug_id)), 0.05)
            dte = r.days_to_expiry_at_decision
            rows.append({
                "batch_id": r.batch_id,
                "stock_level": r.quantity,
                "sales_rate": rate,
                "days_to_expiry": dte,
                "stock_to_sales_ratio": r.quantity / (rate * 7 + 1e-6),
                "inventory_weeks_remaining": r.quantity / (rate * 7 + 1e-6),
                "drug_category": r.category,
                "pharmacy_type": m["pharmacy_type"],
                "historical_expiry_rate": hist_lookup.get(r.category, 0.1),
                "seasonal_index": seasonal_index(r.category, r.decision_date),
                "decision_date": r.decision_date,
                "label_will_expire": int(r.expired_unsold),
            })
        f = pd.DataFrame(rows)
        return f

    # ---- scoring path: currently-live batches, features as of today ----
    batches = db.read_sql("""
        SELECT b.batch_id, b.pharmacy_id, b.drug_id, b.quantity, b.unit_price,
               b.expiry_date, b.received_date, d.category, p.pharmacy_type
        FROM inventory_batches b
        JOIN drugs d ON d.drug_id = b.drug_id
        JOIN pharmacies p ON p.pharmacy_id = b.pharmacy_id
        WHERE b.is_expired = FALSE AND b.quantity > 0
    """)
    if batches.empty:
        return pd.DataFrame()
    batches["expiry_date"] = pd.to_datetime(batches["expiry_date"])

    rate = _recent_rate(as_of)
    batches = batches.merge(rate, on=["pharmacy_id", "drug_id"], how="left")
    batches["daily_rate"] = batches["daily_rate"].fillna(0.05).infer_objects(copy=False)

    # historical rate from the resolved set (stable network estimate)
    resolved = _resolve_expired_unsold(as_of_cutoff=None)
    hist = _historical_expiry_rate_from(resolved)
    batches = batches.merge(hist, on="category", how="left")
    batches["hist_expiry_rate"] = batches["hist_expiry_rate"].fillna(0.1).infer_objects(copy=False)

    f = pd.DataFrame()
    f["batch_id"] = batches["batch_id"]
    f["stock_level"] = batches["quantity"]
    f["sales_rate"] = batches["daily_rate"]
    f["days_to_expiry"] = (batches["expiry_date"] - as_of).dt.days.clip(lower=0)
    f["stock_to_sales_ratio"] = batches["quantity"] / (batches["daily_rate"] * 7 + 1e-6)
    f["inventory_weeks_remaining"] = batches["quantity"] / (batches["daily_rate"] * 7 + 1e-6)
    f["drug_category"] = batches["category"]
    f["pharmacy_type"] = batches["pharmacy_type"]
    f["historical_expiry_rate"] = batches["hist_expiry_rate"]
    f["seasonal_index"] = [seasonal_index(c, as_of) for c in batches["category"]]
    return f


if __name__ == "__main__":
    df = build_feature_table(for_training=True)
    print(f"Resolved training rows: {len(df)}")
    if "label_will_expire" in df and len(df):
        print("Label balance:",
              df["label_will_expire"].value_counts(normalize=True).round(3).to_dict())
        print("Positive (expired-unsold) count:", int(df["label_will_expire"].sum()))
    else:
        print("No resolvable labels.")