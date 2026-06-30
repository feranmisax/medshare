"""
send_monthly_reports.py — emails the dashboard PDF to every pharmacy that has an
email on file. Intended to run on a schedule (see .github/workflows/monthly_reports.yml).

Reads DATABASE_URL and SMTP_* from environment variables. Run manually with:
    python send_monthly_reports.py
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

import pandas as pd
from src import db, dashboard, emailer


def main():
    if not emailer.is_configured():
        print("ERROR: SMTP_* environment variables are not set. Aborting.")
        sys.exit(1)

    targets = db.read_sql("""
        SELECT pharmacy_id, area, email FROM pharmacies
        WHERE email IS NOT NULL AND email <> '' ORDER BY pharmacy_id
    """)
    if targets.empty:
        print("No pharmacies have an email on file. Nothing to send.")
        return

    stamp = pd.Timestamp.today().strftime("%Y%m%d")
    sent, failed = 0, 0
    for _, p in targets.iterrows():
        pid = p["pharmacy_id"]
        try:
            pdf = dashboard.build_pdf(pid, f"{pid} · {p['area']}")
            emailer.send_report(
                p["email"], f"MedShare monthly report — {pid}",
                f"Attached is your monthly MedShare dashboard report for {pid} ({p['area']}).",
                pdf, f"MedShare_{pid}_{stamp}.pdf")
            print(f"  sent -> {pid} ({p['email']})")
            sent += 1
        except Exception as ex:
            print(f"  FAILED -> {pid}: {ex}")
            failed += 1
    print(f"\nDone. {sent} sent, {failed} failed.")


if __name__ == "__main__":
    main()
