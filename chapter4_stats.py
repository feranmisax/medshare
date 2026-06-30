"""
chapter4_stats.py — one-shot operational snapshot for Chapter 4.

Prints every operational figure the results chapter needs, read straight from
whatever database DATABASE_URL points at (set $env:DATABASE_URL to Neon first,
so these match Power BI and the live demo).

Run:  python chapter4_stats.py
"""
from src import db


def one(sql):
    df = db.read_sql(sql)
    return df.iloc[0, 0] if not df.empty else 0


def show(label, value, money=False):
    if money:
        print(f"  {label:<42} ₦{value:,.0f}")
    else:
        print(f"  {label:<42} {value:,}")


def section(title):
    print("\n" + title)
    print("-" * len(title))


print("=" * 60)
print("MEDSHARE — CHAPTER 4 OPERATIONAL SNAPSHOT")
print("=" * 60)

section("NETWORK")
show("Pharmacies (total)", one("SELECT COUNT(*) FROM pharmacies"))
show("  of which real (survey)", one("SELECT COUNT(*) FROM pharmacies WHERE is_synthetic = FALSE"))
show("  of which synthetic", one("SELECT COUNT(*) FROM pharmacies WHERE is_synthetic = TRUE"))
show("Distinct drugs", one("SELECT COUNT(*) FROM drugs"))
show("Live batches (not expired, qty>0)",
     one("SELECT COUNT(*) FROM inventory_batches WHERE is_expired = FALSE AND quantity > 0"))
show("Live stock value",
     one("SELECT COALESCE(SUM(quantity*unit_price),0) FROM inventory_batches WHERE is_expired = FALSE"), money=True)

section("EXPIRY RISK (Model 1, latest scoring snapshot)")
for tier in ("Critical", "High", "Medium", "Low"):
    show(f"{tier} batches",
         one(f"""SELECT COUNT(*) FROM expiry_risk_scores
                 WHERE score_date = (SELECT MAX(score_date) FROM expiry_risk_scores)
                 AND risk_tier = '{tier}'"""))
show("Value at risk (High+Critical)",
     one("""SELECT COALESCE(SUM(b.quantity*b.unit_price),0)
            FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id=r.batch_id
            WHERE r.score_date=(SELECT MAX(score_date) FROM expiry_risk_scores)
            AND r.risk_tier IN ('High','Critical')"""), money=True)

section("MARKETPLACE — RECOMMENDATIONS (Model 3)")
show("Recommendations (total)", one("SELECT COUNT(*) FROM redistribution_recommendations"))
show("  origin = SURPLUS (push)", one("SELECT COUNT(*) FROM redistribution_recommendations WHERE origin='SURPLUS'"))
show("  origin = REQUEST (pull)", one("SELECT COUNT(*) FROM redistribution_recommendations WHERE origin='REQUEST'"))
for st in ("RECOMMENDED", "OFFERED", "ACCEPTED", "DECLINED"):
    show(f"  status = {st}", one(f"SELECT COUNT(*) FROM redistribution_recommendations WHERE status='{st}'"))
acc = one("SELECT COUNT(*) FROM redistribution_recommendations WHERE status='ACCEPTED'")
dec = one("SELECT COUNT(*) FROM redistribution_recommendations WHERE status='DECLINED'")
rate = (acc / (acc + dec) * 100) if (acc + dec) else 0
print(f"  {'Acceptance rate (accepted / acc+dec)':<42} {rate:.1f}%")

section("MARKETPLACE — REQUESTS (pull side)")
show("Requests posted (total)", one("SELECT COUNT(*) FROM stock_requests"))
for st in ("OPEN", "MATCHED", "FULFILLED", "CANCELLED"):
    show(f"  status = {st}", one(f"SELECT COUNT(*) FROM stock_requests WHERE status='{st}'"))

section("TRANSFERS & REVENUE")
show("Completed transfers", one("SELECT COUNT(*) FROM transfers WHERE status='ACCEPTED'"))
show("Units redistributed", one("SELECT COALESCE(SUM(agreed_quantity),0) FROM transfers WHERE status='ACCEPTED'"))
show("Gross transfer value (rescued)",
     one("SELECT COALESCE(SUM(gross_value),0) FROM transfers WHERE status='ACCEPTED'"), money=True)
show("Platform revenue (commission)",
     one("SELECT COALESCE(SUM(commission_amount),0) FROM transfers WHERE status='ACCEPTED'"), money=True)
gv = one("SELECT COALESCE(SUM(gross_value),0) FROM transfers WHERE status='ACCEPTED'")
cm = one("SELECT COALESCE(SUM(commission_amount),0) FROM transfers WHERE status='ACCEPTED'")
print(f"  {'Avg commission %':<42} {(cm/gv*100 if gv else 0):.2f}%")

section("WASTE REGISTRY (expired_stock)")
show("Expired batches logged", one("SELECT COUNT(*) FROM expired_stock"))
show("Units expired", one("SELECT COALESCE(SUM(units_expired),0) FROM expired_stock"))
show("Value lost to expiry",
     one("SELECT COALESCE(SUM(value_lost),0) FROM expired_stock"), money=True)

section("OPERATIONAL RESCUE RATIO (in-app, NOT the Chapter 4 eval figure)")
rescued = gv
lost = one("SELECT COALESCE(SUM(value_lost),0) FROM expired_stock")
denom = rescued + lost
print(f"  {'rescued / (rescued + lost)':<42} {(rescued/denom*100 if denom else 0):.1f}%")
print("  NOTE: cite the evaluate.py figure (~51% vs baseline) as the headline,")
print("        not this operational ratio.")

print("\n" + "=" * 60)
print("Done. Copy this whole output for Chapter 4.")
print("=" * 60)
