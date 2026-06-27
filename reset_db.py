"""
Drop ALL application tables in whatever database DATABASE_URL points at,
so the next `python cloud_setup.py` (or generator+pipeline) rebuilds cleanly.

USAGE (be deliberate — this deletes data):
    python reset_db.py

Works for local or cloud depending on your current DATABASE_URL / .env.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

from sqlalchemy import text
from src import db
import config

# child tables first, then parents (order respects foreign keys)
TABLES = [
    "notifications", "transfers", "redistribution_recommendations",
    "price_negotiations", "demand_forecasts", "expiry_risk_scores",
    "expired_stock", "stock_requests", "sales_daily",
    "inventory_batches", "users", "drugs", "pharmacies",
]


def main():
    where = config.DATABASE_URL.split("@")[-1]
    print(f"About to DROP all tables in: {where}")
    if input("Type 'DROP' to confirm: ").strip() != "DROP":
        print("Cancelled."); return
    with db.engine.begin() as conn:
        for t in TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
            print(f"  dropped {t}")
    print("All tables dropped. Now run: python cloud_setup.py")


if __name__ == "__main__":
    main()