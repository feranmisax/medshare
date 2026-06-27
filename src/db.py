"""Database connection helper. One engine, reused everywhere."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
import pandas as pd
import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)


def run_sql(sql: str, params: dict | None = None):
    """Execute a statement that returns nothing (INSERT/UPDATE/DDL)."""
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def write_df(df: pd.DataFrame, table: str, if_exists: str = "append"):
    """Bulk-load a DataFrame into a table."""
    df.to_sql(table, engine, if_exists=if_exists, index=False, method="multi", chunksize=1000)


def ping() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print("DB connection failed:", e)
        return False


if __name__ == "__main__":
    print("Database reachable:", ping())
