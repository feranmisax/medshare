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
