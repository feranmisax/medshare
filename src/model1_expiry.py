"""
Model 1 — expiry-risk classifier (XGBoost, probability-calibrated).

Trains on the leakage-safe feature table, calibrates probabilities, and writes
a calibrated risk score + tier for every current batch into expiry_risk_scores.
A rule-based override sets tier = 'Critical' when days_to_expiry <= CRITICAL_DAYS
and there is surplus.

Train:  python -m src.model1_expiry --train
Score:  python -m src.model1_expiry --score
"""
import sys, argparse, joblib
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, recall_score, precision_score, brier_score_loss
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

import config
from src import db, features

NUM = ["stock_level","sales_rate","days_to_expiry","stock_to_sales_ratio",
       "inventory_weeks_remaining","historical_expiry_rate","seasonal_index"]
CAT = ["drug_category","pharmacy_type"]
MODEL_PATH = config.MODELS_DIR / "model1_expiry.joblib"


def _make_pipeline():
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CAT),
        ("num", "passthrough", NUM),
    ])
    xgb = XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.9, colsample_bytree=0.9, eval_metric="logloss",
        random_state=config.RANDOM_SEED,
    )
    return Pipeline([("pre", pre), ("clf", xgb)])


def train():
    df = features.build_feature_table(for_training=True)
    if df["label_will_expire"].nunique() < 2:
        print("Only one class present in labels — generate more data or widen SIM_DAYS.")
        return
    X = df[NUM + CAT]
    y = df["label_will_expire"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25,
                                          random_state=config.RANDOM_SEED, stratify=y)
    base = _make_pipeline()
    base.fit(Xtr, ytr)
    # calibrate probabilities (isotonic) on held-out data
    cal = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
    cal.fit(Xte, yte)

    p = cal.predict_proba(Xte)[:, 1]
    pred = (p >= 0.5).astype(int)
    print("AUC-ROC :", round(roc_auc_score(yte, p), 3))
    print("Recall  :", round(recall_score(yte, pred), 3))
    print("Precision:", round(precision_score(yte, pred, zero_division=0), 3))
    print("Brier   :", round(brier_score_loss(yte, p), 3))
    joblib.dump(cal, MODEL_PATH)
    print("Saved model ->", MODEL_PATH)


def _tier(prob):
    for name, lo, hi in config.RISK_TIERS:
        if lo <= prob < hi:
            return name
    return "High"


def score():
    if not MODEL_PATH.exists():
        print("No trained model. Run:  python -m src.model1_expiry --train")
        return
    cal = joblib.load(MODEL_PATH)
    feats = features.build_feature_table(for_training=False)
    if feats.empty:
        print("No batches to score.")
        return
    probs = cal.predict_proba(feats[NUM + CAT])[:, 1]
    out = pd.DataFrame({"batch_id": feats["batch_id"].values,
                        "risk_probability": probs,
                        "days_to_expiry": feats["days_to_expiry"].values})
    out["risk_tier"] = out["risk_probability"].apply(_tier)

    # exclude already-expired batches (0 or negative days) from scoring entirely;
    # the expiry sweep handles those and logs them to the waste registry.
    out = out[out["days_to_expiry"] >= 1].copy()
    if out.empty:
        print("No live batches to score (all remaining are expired).")
        return

    # rule-based Critical override: surplus stock with 1-7 days left (never 0)
    crit = feats[["batch_id","days_to_expiry","stock_level","sales_rate"]].copy()
    crit["surplus"] = crit["stock_level"] > crit["sales_rate"] * crit["days_to_expiry"]
    critical_ids = set(crit.loc[
        (crit["days_to_expiry"] >= 1) &
        (crit["days_to_expiry"] <= config.CRITICAL_DAYS) &
        crit["surplus"], "batch_id"])
    out.loc[out["batch_id"].isin(critical_ids), "risk_tier"] = "Critical"

    out = out.drop(columns=["days_to_expiry"])
    out["score_date"] = pd.Timestamp.today().date()
    out["model_version"] = "v1"
    db.run_sql("DELETE FROM expiry_risk_scores WHERE score_date = CURRENT_DATE")
    db.write_df(out, "expiry_risk_scores")
    print(f"Scored {len(out)} live batches. Tier counts:")
    print(out["risk_tier"].value_counts().to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if a.train: train()
    if a.score: score()
    if not (a.train or a.score): print("Use --train and/or --score")
