"""
Feature engineering for the expiry-risk classifier (Model 1).

The nine features (Chapter 3, Table 3.5):
  stock_level, sales_rate, days_to_expiry, stock_to_sales_ratio,
  inventory_weeks_remaining, drug_category, pharmacy_type,
  historical_expiry_rate, seasonal_index

Leakage-safe label: a batch is labelled "will expire" (1) if its quantity exceeds
the demand it can realistically absorb over its remaining shelf life. Demand is
estimated from PAST sales only (the recent average), never from future data.

Run (for a quick look):  python -m src.features
"""
import sys, math
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from src import db


def _seasonal_index(d: pd.Timestamp) -> float:
    return float(1.0 + 0.15 * math.sin(2 * math.pi * (d.dayofyear - 120) / 365.0))


def build_feature_table(as_of: pd.Timestamp | None = None, for_training: bool = True) -> pd.DataFrame:
    as_of = pd.Timestamp(as_of or pd.Timestamp.today().normalize())

    batches = db.read_sql("""
        SELECT b.batch_id, b.pharmacy_id, b.drug_id, b.quantity, b.unit_price,
               b.expiry_date, b.received_date, d.category, p.pharmacy_type
        FROM inventory_batches b
        JOIN drugs d ON d.drug_id = b.drug_id
        JOIN pharmacies p ON p.pharmacy_id = b.pharmacy_id
        WHERE b.is_expired = FALSE AND b.quantity > 0
    """)
    batches["expiry_date"] = pd.to_datetime(batches["expiry_date"])
    batches["received_date"] = pd.to_datetime(batches["received_date"])

    # recent daily sales rate per (pharmacy, drug) from the last 28 days BEFORE as_of
    rate = db.read_sql("""
        SELECT pharmacy_id, drug_id, AVG(units_sold) AS daily_rate
        FROM sales_daily
        WHERE sale_date < :as_of AND sale_date >= :start
        GROUP BY pharmacy_id, drug_id
    """, {"as_of": as_of.date(), "start": (as_of - pd.Timedelta(days=28)).date()})
    batches = batches.merge(rate, on=["pharmacy_id","drug_id"], how="left")
    batches["daily_rate"] = batches["daily_rate"].fillna(0.05)

    # historical expiry rate per category (share of past batches that lapsed) — past only
    hist = db.read_sql("""
        SELECT d.category,
               AVG(CASE WHEN b.expiry_date < :as_of THEN 1 ELSE 0 END) AS hist_expiry_rate
        FROM inventory_batches b JOIN drugs d ON d.drug_id = b.drug_id
        GROUP BY d.category
    """, {"as_of": as_of.date()})
    batches = batches.merge(hist, on="category", how="left")
    batches["hist_expiry_rate"] = batches["hist_expiry_rate"].fillna(0.1)

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
    f["seasonal_index"] = _seasonal_index(as_of)

    if for_training:
        # leakage-safe label: demand absorbable over remaining shelf life (past rate)
        absorbable = batches["daily_rate"] * f["days_to_expiry"]
        f["label_will_expire"] = (batches["quantity"] > absorbable * 1.0).astype(int)
        # keep only batches that have a future expiry to learn from
        f = f[f["days_to_expiry"] >= 0]
    return f


if __name__ == "__main__":
    df = build_feature_table()
    print(df.head())
    print("\nLabel balance:", df["label_will_expire"].value_counts(normalize=True).round(3).to_dict()
          if "label_will_expire" in df else "n/a")
