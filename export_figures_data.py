"""
export_figures_data.py — one-shot export of the data behind the Chapter 4
analytical figures. Run against the SAME database your results came from
(set DATABASE_URL to Neon first, so the figures match the thesis numbers):

    python export_figures_data.py

Writes CSVs into ./figure_data/ :
    roc_points.csv          FPR/TPR for LR, RF, XGBoost, Oracle  (ROC + ceiling)
    model_summary.csv       AUC per model + oracle               (annotate ROC)
    calibration.csv         mean predicted vs observed freq (XGBoost)  (reliability)
    confusion.csv           TN/FP/FN/TP at the operating threshold
    feature_importance.csv  XGBoost gain importance per feature
    test_predictions.csv    per-batch y_true + predicted prob (for any custom plot)
    forecast_actual.csv     forecast q10/q50/q90 vs actual for sample series (overlay)

Upload the whole figure_data/ folder (or zip it) and the figures get built from it.
Nothing here retrains your saved model or changes the database — it only reads.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config
from src import db, features
from src import model1_expiry as m1

from sklearn.metrics import roc_curve, roc_auc_score, confusion_matrix
from sklearn.calibration import calibration_curve

OUT = Path(__file__).resolve().parent / "figure_data"
OUT.mkdir(exist_ok=True)

NUM, CAT = m1.NUM, m1.CAT


def _fit_predict(factory, Xtr, ytr, Xte):
    """Reproduce model1's fit+calibrate, return test-set probabilities."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import train_test_split
    Xf, Xc, yf, yc = train_test_split(
        Xtr, ytr, test_size=0.25, random_state=config.RANDOM_SEED, stratify=ytr)
    p = factory()
    p.fit(Xf, yf)
    try:
        cal = CalibratedClassifierCV(p, method="isotonic", cv="prefit")
        cal.fit(Xc, yc)
        return cal.predict_proba(Xte)[:, 1], cal
    except Exception:
        p.fit(Xtr, ytr)
        return p.predict_proba(Xte)[:, 1], p


def main():
    print(f"Reading database: {config.DATABASE_URL.split('@')[-1]}")
    as_of = pd.Timestamp.today().normalize()
    df = features.build_feature_table(as_of=as_of, for_training=True)
    if df.empty or df["label_will_expire"].nunique() < 2:
        print("Need both label classes. Generate data / widen SIM_DAYS first.")
        return

    train_df, test_df = m1._temporal_split(df, as_of, cutoff=0.6)
    Xtr, ytr = train_df[NUM + CAT], train_df["label_will_expire"]
    Xte, yte = test_df[NUM + CAT], test_df["label_will_expire"].values
    print(f"Train {len(Xtr)}  Test {len(Xte)}  positives(test)={yte.mean():.1%}")

    # ---- fit the three models, collect test probabilities ----
    probs = {}
    p_lr, _ = _fit_predict(m1._lr_factory, Xtr, ytr, Xte); probs["LogisticRegression"] = p_lr
    p_rf, _ = _fit_predict(m1._rf_factory, Xtr, ytr, Xte); probs["RandomForest"] = p_rf
    p_xgb, cal_xgb = _fit_predict(m1._make_pipeline, Xtr, ytr, Xte); probs["XGBoost"] = p_xgb

    # oracle proxy (same formula as model1.train)
    oracle = (test_df["stock_level"] /
              (test_df["sales_rate"] * test_df["days_to_expiry"].clip(lower=1) + 1e-6)).values
    probs["Oracle"] = oracle

    # ---- ROC points + AUC summary ----
    roc_rows, summ = [], []
    for name, p in probs.items():
        fpr, tpr, _ = roc_curve(yte, p)
        auc = roc_auc_score(yte, p)
        summ.append({"model": name, "auc": round(auc, 4)})
        for f, t in zip(fpr, tpr):
            roc_rows.append({"model": name, "fpr": f, "tpr": t})
    pd.DataFrame(roc_rows).to_csv(OUT / "roc_points.csv", index=False)
    pd.DataFrame(summ).to_csv(OUT / "model_summary.csv", index=False)
    print("  wrote roc_points.csv, model_summary.csv")

    # ---- calibration (reliability) for adopted XGBoost ----
    frac_pos, mean_pred = calibration_curve(yte, p_xgb, n_bins=10, strategy="quantile")
    pd.DataFrame({"mean_predicted": mean_pred,
                  "observed_frequency": frac_pos}).to_csv(OUT / "calibration.csv", index=False)
    print("  wrote calibration.csv")

    # ---- confusion matrix at 0.5 threshold ----
    pred = (p_xgb >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(yte, pred).ravel()
    pd.DataFrame([{"TN": tn, "FP": fp, "FN": fn, "TP": tp,
                   "threshold": 0.5}]).to_csv(OUT / "confusion.csv", index=False)
    print(f"  wrote confusion.csv  (TN={tn} FP={fp} FN={fn} TP={tp})")

    # ---- per-batch test predictions (for any custom figure) ----
    pd.DataFrame({"y_true": yte, "prob_xgb": p_xgb,
                  "prob_lr": p_lr, "prob_rf": p_rf}).to_csv(
        OUT / "test_predictions.csv", index=False)
    print("  wrote test_predictions.csv")

    # ---- feature importance (XGBoost gain) ----
    try:
        # dig the fitted XGB out of the calibrated pipeline
        booster = None
        est = cal_xgb
        # CalibratedClassifierCV(prefit) wraps the pipeline in .estimator
        pipe = getattr(est, "estimator", None) or getattr(est, "base_estimator", None)
        if pipe is not None:
            clf = pipe.named_steps.get("clf")
            pre = pipe.named_steps.get("pre")
            # expand one-hot feature names
            ohe = pre.named_transformers_["cat"]
            cat_names = list(ohe.get_feature_names_out(CAT))
            feat_names = cat_names + NUM
            imp = clf.feature_importances_
            fi = pd.DataFrame({"feature": feat_names[:len(imp)],
                               "importance": imp}).sort_values("importance", ascending=False)
            fi.to_csv(OUT / "feature_importance.csv", index=False)
            print("  wrote feature_importance.csv")
    except Exception as e:
        print(f"  (feature_importance skipped: {e})")

    # ---- forecast vs actual overlay for a few sample series ----
    try:
        fc = db.read_sql("""
            SELECT f.pharmacy_id, f.drug_id, f.q10, f.q50, f.q90,
                   d.name AS drug
            FROM demand_forecasts f JOIN drugs d ON d.drug_id=f.drug_id
            WHERE f.forecast_date = (SELECT MAX(forecast_date) FROM demand_forecasts)
        """)
        # pick 6 series with the most sales history
        top = db.read_sql("""
            SELECT pharmacy_id, drug_id, COUNT(*) n, AVG(units_sold) avg_units
            FROM sales_daily GROUP BY pharmacy_id, drug_id
            ORDER BY n DESC, avg_units DESC LIMIT 6
        """)
        rows = []
        for r in top.itertuples():
            hist = db.read_sql("""
                SELECT sale_date, units_sold FROM sales_daily
                WHERE pharmacy_id = :pid AND drug_id = :did
                ORDER BY sale_date""", {"pid": r.pharmacy_id, "did": int(r.drug_id)})
            f = fc[(fc.pharmacy_id == r.pharmacy_id) & (fc.drug_id == r.drug_id)]
            if hist.empty or f.empty:
                continue
            key = f"{r.pharmacy_id}-{r.drug_id}"
            for h in hist.itertuples():
                rows.append({"series": key, "date": h.sale_date,
                             "actual": h.units_sold, "q10": None, "q50": None, "q90": None})
            fr = f.iloc[0]
            rows.append({"series": key, "date": "FORECAST",
                         "actual": None, "q10": fr.q10, "q50": fr.q50, "q90": fr.q90})
        if rows:
            pd.DataFrame(rows).to_csv(OUT / "forecast_actual.csv", index=False)
            print("  wrote forecast_actual.csv")
    except Exception as e:
        print(f"  (forecast_actual skipped: {e})")

    print(f"\nDone. Upload the folder: {OUT}")


if __name__ == "__main__":
    main()