"""Central configuration. Reads .env (local) or Streamlit secrets (cloud)."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _get(key, default=None):
    """Prefer real env vars (.env / shell); fall back to Streamlit Cloud secrets."""
    val = os.getenv(key)
    if val is not None:
        return val
    try:
        import streamlit as st  # only available when running under Streamlit
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


DATABASE_URL = _get("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/pharma_redist")

N_PHARMACIES = int(_get("N_PHARMACIES", 150))
SIM_DAYS = int(_get("SIM_DAYS", 180))
RANDOM_SEED = int(os.getenv("RANDOM_SEED", 42))

MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", 0.65))
K_NEAREST = int(os.getenv("K_NEAREST", 10))
MAX_DISTANCE_KM = float(os.getenv("MAX_DISTANCE_KM", 20))
SERVICE_LEVEL = float(os.getenv("SERVICE_LEVEL", 0.8))

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))

DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

# Risk tiers (calibrated-probability cutoffs for Model 1)
RISK_TIERS = [("Low", 0.0, 0.33), ("Medium", 0.33, 0.66), ("High", 0.66, 1.01)]
CRITICAL_DAYS = 7  # rule-based override: <= this many days to expiry + surplus => Critical
MIN_REDISTRIBUTABLE_DAYS = 3  # batches with fewer days left than this cannot be redistributed
                              # in time (match + offer + transfer + use), so they are treated as
                              # a loss and excluded from at-risk redistribution listings.

# ---------------------------------------------------------------------------
# Realistic, category-varying shelf lives (months) for batch expiry generation.
# Different drug classes carry very different shelf lives; modelling this gives
# the simulated shelf a realistic spread (most stock far from expiry, a minority
# near-term) instead of everything clustered near expiry. (Chapter 3, §3.1.5.)
# (low, high) months — a batch's shelf life is drawn uniformly in this range.
SHELF_LIFE_MONTHS = {
    "Antibiotics":            (18, 30),
    "Antimalarials":          (18, 30),
    "Analgesics":             (36, 60),
    "Antihypertensives":      (24, 48),
    "Antidiabetics":          (24, 48),
    "Antacids/GI":            (24, 42),
    "Vitamins/Supplements":   (24, 42),
    "Cough/Cold":             (18, 36),
}
DEFAULT_SHELF_LIFE_MONTHS = (24, 42)

# Fraction of batches deliberately drawn "near-term" (already partway through
# shelf life) so that a realistic minority of stock is genuinely at risk during
# the simulation window while the majority sits comfortably far from expiry.
NEAR_TERM_BATCH_FRACTION = 0.30

# Category x month seasonal demand multipliers (rainy-season antimalarial uplift,
# cough/cold uplift in harmattan, etc.). Used by BOTH the generator and the
# feature builder so seasonal_index is a real, varying feature — not a constant.
# Month index 1..12 -> multiplier. Values default to 1.0 where unspecified.
SEASONAL_BY_CATEGORY = {
    "Antimalarials":  {5:1.25, 6:1.35, 7:1.40, 8:1.35, 9:1.25, 10:1.15},   # rainy season
    "Cough/Cold":     {11:1.20, 12:1.30, 1:1.30, 2:1.20},                    # harmattan
    "Antibiotics":    {6:1.10, 7:1.15, 8:1.10},
}

# NAFDAC validation-only integration (Chapter 3, §3.1.4). If a curated snapshot
# file is present, the generator will VALIDATE its catalogue names against it
# (cross-check that each drug is a registered product) and optionally enrich
# with registration metadata. If the file is absent, the pipeline is unaffected.
NAFDAC_CATALOGUE_FILE = DATA_DIR / "nafdac_catalogue.csv"

# Evaluation sweeps (Chapter 3, §3.5.3-3.5.4)
ACCEPTANCE_SWEEP = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
B1_CLEAR_SWEEP   = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
DEFAULT_ACCEPTANCE = 0.64   # survey-anchored point estimate (reported within the curve)
DEFAULT_B1_CLEAR   = 0.15   # assumed status-quo informal-clearance fraction
