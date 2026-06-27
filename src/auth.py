"""
Authentication + multi-tenant user management.

Each pharmacy gets a login (PCN number as username). Operators see only their own
pharmacy's data; an 'admin' (management) account can view any pharmacy.

Seed demo accounts:  python -m src.auth --seed
  - every pharmacy: username = its pharmacy_id (e.g. PH001), password = 'medshare'
  - management:      username = 'admin', password = 'admin123'
"""
import sys, argparse
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from passlib.hash import pbkdf2_sha256
from src import db


def hash_pw(pw: str) -> str:
    return pbkdf2_sha256.hash(pw)


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return pbkdf2_sha256.verify(pw, hashed)
    except Exception:
        return False


def authenticate(pcn: str, pw: str):
    """Return dict(pharmacy_id, role, pcn) on success, else None."""
    rows = db.read_sql(
        "SELECT pharmacy_id, pcn_number, password_hash, role FROM users WHERE pcn_number = :u",
        {"u": pcn.strip()})
    if rows.empty:
        return None
    r = rows.iloc[0]
    if verify_pw(pw, r["password_hash"]):
        return {"pharmacy_id": r["pharmacy_id"], "role": r["role"], "pcn": r["pcn_number"]}
    return None


def create_user(pharmacy_id: str, pcn: str, pw: str, role: str = "pharmacy"):
    db.run_sql("""
        INSERT INTO users (pharmacy_id, pcn_number, password_hash, role)
        VALUES (:pid, :pcn, :h, :role)
        ON CONFLICT (pcn_number) DO NOTHING
    """, {"pid": pharmacy_id, "pcn": pcn, "h": hash_pw(pw), "role": role})


# ---------------- session tokens (persist login across browser refresh) ----------------
import hmac, hashlib, base64, json, time

_SECRET = "medshare-demo-secret-change-in-production"   # move to .env for the pilot
INACTIVITY_SECONDS = 600                                # 10 minutes


def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{raw}.{sig}"


def make_token(pcn: str) -> str:
    return _sign({"pcn": pcn, "ts": int(time.time())})


def read_token(token: str):
    """Return the user dict if the token is valid and not timed out, else None."""
    try:
        raw, sig = token.split(".")
        expected = hmac.new(_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if time.time() - payload["ts"] > INACTIVITY_SECONDS:
            return None                                  # inactivity timeout
        rows = db.read_sql(
            "SELECT pharmacy_id, pcn_number, role FROM users WHERE pcn_number = :u",
            {"u": payload["pcn"]})
        if rows.empty:
            return None
        r = rows.iloc[0]
        return {"pharmacy_id": r["pharmacy_id"], "role": r["role"], "pcn": r["pcn_number"]}
    except Exception:
        return None


def seed_demo_users():
    phs = db.read_sql("SELECT pharmacy_id FROM pharmacies ORDER BY pharmacy_id")
    if phs.empty:
        print("No pharmacies found. Run the generator first.")
        return
    n = 0
    for pid in phs["pharmacy_id"]:
        create_user(pid, pid, "medshare", "pharmacy")
        n += 1
    # management account (home pharmacy = first, but role admin can view all)
    create_user(phs.iloc[0]["pharmacy_id"], "admin", "admin123", "admin")
    print(f"Seeded {n} pharmacy logins (password 'medshare') + 1 admin (admin / admin123).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args()
    if a.seed:
        seed_demo_users()
    else:
        print("Use --seed to create demo logins.")
