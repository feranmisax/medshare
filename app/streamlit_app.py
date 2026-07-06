"""
MedShare — multi-tenant pharmacy redistribution marketplace.

Login (PCN + password) -> each pharmacy sees ONLY its own data. Admin can view any.
Flow: surplus/request -> source OFFERS -> target ACCEPTS -> transfer + platform commission.

Run:  streamlit run app/streamlit_app.py
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px

from src import db, auth, requests_match, model3_matching, dashboard

st.set_page_config(page_title="MedShare", page_icon="✚", layout="wide",
                   initial_sidebar_state="expanded")

COMMISSION_RATE = 0.05  # platform fee on completed transfers

# ----------------------------- theme -----------------------------
choice = st.session_state.get("theme_choice", "☀️ Light")
dark = (choice == "🌙 Dark")
THEME = ("""
:root{ color-scheme:dark;
  --paper:#0E1F1A; --surface:#16302A; --field:#0C1F1A; --ink:#F5FAF8; --muted:#C4D6D0;
  --brand:#4ECbA8; --brand-soft:#1d3a33; --line:#33524A;
  --crit:#FF8A80; --high:#FFC04D; --med:#6FE0C6; --low:#9FB4AD; }
""" if dark else """
:root{ color-scheme:light;
  --paper:#F4F1EA; --surface:#FFFFFF; --field:#FFFFFF; --ink:#0C211D; --muted:#3D544D;
  --brand:#0C5F4F; --brand-soft:#E4F0EC; --line:#D8D1C4;
  --crit:#9A1B14; --high:#8A5800; --med:#1F6657; --low:#5E6F69; }
""")
st.markdown(f"<style>{THEME}</style>", unsafe_allow_html=True)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600;700&display=swap');
[data-testid="stHeader"], [data-testid="stDecoration"], [data-testid="stToolbar"]{ display:none !important; }
#MainMenu, footer{ visibility:hidden; }
html, body, [class*="css"]{ font-family:'Inter',system-ui,sans-serif; }
.stApp{ background:var(--paper); color:var(--ink); }
.block-container{ max-width:100% !important; padding:1.1rem 2.4rem 3rem 2.4rem; }
[data-testid="stMarkdownContainer"], label, p, span{ color:var(--ink); }
[data-testid="stCaptionContainer"], .stCaption{ color:var(--muted) !important; }
[data-testid="stNumberInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="base-input"],
[data-baseweb="select"] > div, [data-testid="stTextInput"] [data-baseweb="input"]{
  background:var(--field) !important; border:1px solid var(--line) !important; border-radius:8px !important;
  min-height:52px !important; }
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input{
  background:var(--field) !important; color:var(--ink) !important; -webkit-text-fill-color:var(--ink) !important;
  font-size:1.05rem !important; }
[data-testid="stNumberInput"] button{ background:var(--surface) !important; color:var(--ink) !important; border-color:var(--line) !important; }
[data-baseweb="select"] *{ color:var(--ink) !important; }
.brandmark{ display:flex; align-items:center; gap:10px; padding:10px 4px; line-height:1.4; min-height:44px; }
.brandmark .wm{ font-family:'Fraunces',serif; font-weight:600; font-size:1.5rem; line-height:1.4; color:var(--brand); display:inline-block; padding:2px 0; }
.eyebrow{ text-transform:uppercase; letter-spacing:.14em; font-size:.72rem; font-weight:600; color:var(--brand); margin-top:.4rem; }
.wordmark{ font-family:'Fraunces',serif; font-weight:600; font-size:2.3rem; color:var(--ink); letter-spacing:-0.02em; line-height:1; margin:.15rem 0 0; }
.tagline{ color:var(--muted); font-size:.95rem; margin:.4rem 0 0; }
.kpis{ display:flex; gap:14px; flex-wrap:wrap; margin:1.2rem 0 .2rem; }
.kpi{ flex:1; min-width:160px; background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:16px 18px; position:relative; overflow:hidden; }
.kpi::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--brand); }
.kpi.alert::before{ background:var(--high); } .kpi.crit::before{ background:var(--crit); }
.kpi .v{ font-family:'Fraunces',serif; font-size:2.0rem; font-weight:600; color:var(--ink); line-height:1; }
.kpi .l{ font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-top:8px; }
.pill{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:.72rem; font-weight:600; }
.t-Critical{ background:var(--crit); color:#fff; } .t-High{ background:var(--high); color:#fff; }
.t-Medium{ background:var(--med); color:#fff; } .t-Low{ background:var(--low); color:#fff; }
.b-REQUEST{ background:var(--brand-soft); color:var(--brand); border:1px solid var(--brand); }
.b-SURPLUS{ background:var(--surface); color:var(--muted); border:1px solid var(--line); }
.chip{ display:inline-block; padding:2px 10px; border-radius:8px; font-size:.74rem; font-weight:600; border:1px solid var(--line); }
.chip.red{ color:var(--crit); } .chip.amber{ color:var(--high); } .chip.green{ color:var(--med); }
.drug{ font-weight:600; color:var(--ink); font-size:1.05rem; }
.meta{ color:var(--muted); font-size:.82rem; margin-top:2px; }
.route{ font-weight:600; color:var(--ink); } .arrow{ color:var(--brand); font-weight:700; padding:0 6px; }
.total-box{ background:var(--field); border:1px solid var(--line); border-radius:8px; padding:0 12px; height:52px; margin-top:12px; display:flex; flex-direction:column; justify-content:center; }
.total-l{ color:var(--muted); font-size:.6rem; text-transform:uppercase; letter-spacing:.05em; line-height:1.1; }
.total-v{ color:var(--ink); font-weight:700; font-size:.95rem; font-family:'Fraunces',serif; line-height:1.1; white-space:nowrap; }
.card{ background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:14px 18px; margin-bottom:10px; }
section[data-testid="stSidebar"]{ background:var(--surface); border-right:1px solid var(--line); }
.stTabs [data-baseweb="tab-list"]{ gap:8px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
.stTabs [data-baseweb="tab"]{ font-weight:600; color:var(--muted); padding:6px 2px; }
.stTabs [aria-selected="true"]{ color:var(--brand) !important; }
.stTabs [data-baseweb="tab-highlight"]{ background:var(--brand); }
div[role="radiogroup"]{ justify-content:flex-end; gap:10px; }
.stButton>button{ border-radius:10px; font-weight:600; border:none; padding:.5rem 1rem; min-height:52px; }
/* nudge buttons down to align with the total-value box */
.stButton>button{ margin-top:12px; }
.stButton>button[kind="primary"]{ background:var(--brand); color:#fff; }
.stButton>button[kind="primary"]:hover{ filter:brightness(0.92); }
.stButton>button[kind="secondary"]{ background:var(--brand-soft); color:var(--brand); }
div[data-testid="stVerticalBlockBorderWrapper"]{ background:var(--surface); border:1px solid var(--line) !important; border-radius:14px; }
/* remove border only from nested st.container wrappers (the empty outlines), keep input field borders */
div[data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlockBorderWrapper"]{ border:none !important; background:transparent !important; }
/* the total-box draws its own border; ensure its markdown wrapper adds none */
[data-testid="stMarkdownContainer"]:has(.total-box){ border:none !important; background:transparent !important; padding:0 !important; }
@media (prefers-reduced-motion: reduce){ *{ transition:none !important; } }
</style>
""", unsafe_allow_html=True)

CAPSULE = """<svg width="30" height="30" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
<g transform="rotate(-38 20 20)"><rect x="6" y="13" width="14" height="14" rx="7" fill="#0F6E5C"/>
<rect x="20" y="13" width="14" height="14" rx="7" fill="#C8861A"/></g></svg>"""

if not db.ping():
    st.error("Database not reachable. Start PostgreSQL and check your .env, then refresh.")
    st.stop()

# ----------------------------- LOGIN GATE -----------------------------
if "auth" not in st.session_state:
    st.session_state.auth = None

# Try to restore a session from the URL token (survives browser refresh).
if st.session_state.auth is None:
    tok = st.query_params.get("s")
    if tok:
        restored = auth.read_token(tok)
        if restored:
            st.session_state.auth = restored

if st.session_state.auth is None:
    st.query_params.clear()
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown(f'<div class="brandmark" style="justify-content:center">{CAPSULE}<span class="wm">MedShare</span></div>',
                    unsafe_allow_html=True)
        st.markdown('<p class="tagline" style="text-align:center">Sign in to your pharmacy</p>', unsafe_allow_html=True)
        with st.container(border=True):
            pcn = st.text_input("PCN number (username)")
            pw = st.text_input("Password", type="password")
            if st.button("Sign in", type="primary", use_container_width=True):
                u = auth.authenticate(pcn, pw)
                if u:
                    st.session_state.auth = u
                    st.query_params["s"] = auth.make_token(u["pcn"])
                    st.rerun()
                else:
                    st.error("Invalid PCN or password.")
        st.caption("Demo: username = your pharmacy ID (e.g. PH001), password = medshare. Management: admin / admin123.")
    st.stop()

USER = st.session_state.auth
# renew the session token on every run (sliding 10-min inactivity window)
st.query_params["s"] = auth.make_token(USER["pcn"])
phs = db.read_sql("SELECT pharmacy_id, name, area, pharmacy_type FROM pharmacies ORDER BY pharmacy_id")
idx = phs.set_index("pharmacy_id")

# ----------------------------- sidebar -----------------------------
with st.sidebar:
    st.markdown('<div style="font-family:Fraunces,serif;font-size:1.1rem">Signed in</div>', unsafe_allow_html=True)
    if USER["role"] == "admin":
        st.caption("Management view — you can see any pharmacy.")
        pick = st.selectbox("Viewing pharmacy", options=list(phs["pharmacy_id"]),
                            format_func=lambda pid: f"{pid} — {idx.loc[pid,'area']}")
    else:
        pick = USER["pharmacy_id"]
        st.markdown(f"**{pick}** · {idx.loc[pick,'area']}")
        st.caption("You can see only your own pharmacy's data.")
    st.divider()
    notes = db.read_sql("""SELECT id, message, created_at FROM notifications
                           WHERE pharmacy_id=:p AND read_at IS NULL
                           ORDER BY created_at DESC LIMIT 20""", {"p": pick})
    st.markdown(f"**🔔 Notifications ({len(notes)})**")
    if notes.empty:
        st.caption("No new notifications.")
    else:
        for _, n in notes.head(6).iterrows():
            st.markdown(f"<div class='meta' style='margin-bottom:6px'>{n['message']}</div>", unsafe_allow_html=True)
        if st.button("Mark all read", use_container_width=True):
            db.run_sql("UPDATE notifications SET read_at=NOW() WHERE pharmacy_id=:p AND read_at IS NULL", {"p": pick})
            st.rerun()
    st.divider()
    rc1, rc2 = st.columns([1, 1])
    if rc1.button("↻ Refresh", use_container_width=True):
        st.rerun()
    auto = rc2.toggle("Auto", value=st.session_state.get("auto_refresh", False), key="auto_refresh",
                      help="Auto-reload every 8s to catch new offers. Note: resets to the first tab and interrupts typing — best on a window that's only watching for incoming offers.")
    st.divider()
    if st.button("Sign out", use_container_width=True):
        st.session_state.auth = None
        st.query_params.clear()
        st.rerun()

# auto-refresh every ~8s so offers/notifications appear without manual action
if st.session_state.get("auto_refresh", False):
    components.html(
        "<script>setTimeout(function(){window.parent.location.reload();}, 8000);</script>",
        height=0)

me = idx.loc[pick]

# ----------------------------- top bar -----------------------------
left, right = st.columns([7, 3], vertical_alignment="center")
with left:
    st.markdown(f'<div class="brandmark">{CAPSULE}<span class="wm">MedShare</span></div>', unsafe_allow_html=True)
with right:
    st.radio("Theme", ["☀️ Light", "🌙 Dark"], horizontal=True, key="theme_choice", label_visibility="collapsed")

st.markdown(f"""<div class="eyebrow">Signed in as</div>
<h1 class="wordmark">{pick}</h1>
<p class="tagline">{me['area']} · {me['pharmacy_type']}</p>""", unsafe_allow_html=True)

# ----------------------------- KPIs -----------------------------
k = db.read_sql("""
  SELECT
    (SELECT COUNT(*) FROM inventory_batches WHERE pharmacy_id=:p AND is_expired=FALSE AND quantity>0) AS my_batches,
    (SELECT COUNT(*) FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id=r.batch_id
      WHERE b.pharmacy_id=:p AND r.score_date=(SELECT MAX(score_date) FROM expiry_risk_scores) AND r.risk_tier IN ('High','Critical')
        AND b.expiry_date >= CURRENT_DATE + INTERVAL '3 days') AS at_risk,
    (SELECT COUNT(*) FROM redistribution_recommendations
      WHERE source_pharmacy_id=:p AND status='RECOMMENDED' AND origin='SURPLUS') AS to_act,
    (SELECT COUNT(*) FROM redistribution_recommendations
      WHERE source_pharmacy_id=:p AND status='RECOMMENDED' AND origin='REQUEST') AS to_fulfil,
    (SELECT COUNT(*) FROM redistribution_recommendations
      WHERE target_pharmacy_id=:p AND status='OFFERED') AS offers,
    (SELECT COALESCE(SUM(commission_amount),0) FROM transfers t
       JOIN redistribution_recommendations rr ON rr.rec_id=t.rec_id
       WHERE rr.source_pharmacy_id=:p OR rr.target_pharmacy_id=:p) AS my_fees
""", {"p": pick}).iloc[0]

st.markdown(f"""
<div class="kpis">
  <div class="kpi"><div class="v">{int(k['my_batches'])}</div><div class="l">Batches in stock</div></div>
  <div class="kpi {'crit' if int(k['at_risk'])>0 else ''}"><div class="v">{int(k['at_risk'])}</div><div class="l">At risk</div></div>
  <div class="kpi"><div class="v">{int(k['to_act'])}</div><div class="l">To offer</div></div>
  <div class="kpi {'alert' if int(k['to_fulfil'])>0 else ''}"><div class="v">{int(k['to_fulfil'])}</div><div class="l">Requests to fulfil</div></div>
  <div class="kpi {'alert' if int(k['offers'])>0 else ''}"><div class="v">{int(k['offers'])}</div><div class="l">Offers to accept</div></div>
</div>
""", unsafe_allow_html=True)

def notify(pharmacy_id, message, rec_id=None):
    """Single place all notifications go through, for consistency."""
    db.run_sql("""INSERT INTO notifications (pharmacy_id,channel,message,related_rec_id)
                  VALUES (:p,'in_app',:m,:r)""",
               {"p": pharmacy_id, "m": message, "r": (int(rec_id) if rec_id is not None else None)})

def offer_card(r, prefix):
    """Source side: review, adjust, and SEND OFFER (RECOMMENDED -> OFFERED)."""
    badge = f"<span class='pill b-{r['origin']}'>{'Request' if r['origin']=='REQUEST' else 'Surplus'}</span>"
    with st.container(border=True):
        st.markdown(f"<div class='drug'>{r['drug']} {badge}</div>"
                    f"<div class='meta'><span class='route'>{pick}</span><span class='arrow'>→</span>"
                    f"<span class='route'>{r['other']}</span> · {r['km']} km away</div>",
                    unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns([1.4, 1.4, 1.5, 1, 1], vertical_alignment="top")
        maxq = int(max(int(r['available']), int(r['quantity'])))
        qty = c1.number_input("Quantity (units)", 1, maxq, int(r['quantity']), 1, key=f"q{prefix}{r['rec_id']}")
        price = c2.number_input("Price (₦/unit)", 0.0, value=float(r['suggested_price']), step=10.0,
                               format="%.2f", key=f"p{prefix}{r['rec_id']}")
        c3.markdown(f"<div class='total-box'><div class='total-l'>Total value</div><div class='total-v'>₦{qty*price:,.0f}</div></div>", unsafe_allow_html=True)
        send = c4.button("Send offer", key=f"of{prefix}{r['rec_id']}", type="primary", use_container_width=True)
        decline = c5.button("Decline", key=f"dc{prefix}{r['rec_id']}", use_container_width=True)
        if send:
            db.run_sql("""UPDATE redistribution_recommendations
                          SET status='OFFERED', quantity=:q, suggested_price=:pr WHERE rec_id=:r""",
                       {"q": int(qty), "pr": float(price), "r": int(r['rec_id'])})
            notify(r['other'], f"New offer: {int(qty)} units of {r['drug']} from {pick}.", r['rec_id'])
            notify(pick, f"You sent an offer of {int(qty)} units of {r['drug']} to {r['other']}.", r['rec_id'])
            st.toast("Offer sent to the other pharmacy."); st.rerun()
        if decline:
            db.run_sql("UPDATE redistribution_recommendations SET status='DECLINED' WHERE rec_id=:r", {"r": int(r['rec_id'])})
            notify(r['other'], f"{pick} passed on the suggested transfer of {r['drug']}.", r['rec_id'])
            notify(pick, f"You declined the suggestion to send {r['drug']} to {r['other']}.", r['rec_id'])
            st.rerun()

def accept_card(r):
    """Target side: ACCEPT an OFFERED transfer -> create transfer + commission."""
    badge = f"<span class='pill b-{r['origin']}'>{'You requested' if r['origin']=='REQUEST' else 'Offered'}</span>"
    with st.container(border=True):
        st.markdown(f"<div class='drug'>{r['drug']} {badge}</div>"
                    f"<div class='meta'><span class='route'>{r['other']}</span><span class='arrow'>→</span>"
                    f"<span class='route'>{pick}</span> · {r['km']} km · {int(r['quantity'])} units · "
                    f"₦{r['suggested_price']:.0f}/unit</div>", unsafe_allow_html=True)
        gross = float(r['quantity']) * float(r['suggested_price'])
        fee = round(gross * COMMISSION_RATE, 2)
        c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
        c1.markdown(f"<div class='total-box'><div class='total-l'>Total · platform fee {COMMISSION_RATE:.0%}</div><div class='total-v'>₦{gross:,.0f} · fee ₦{fee:,.0f}</div></div>", unsafe_allow_html=True)
        if c2.button("Accept", key=f"ac{r['rec_id']}", type="primary", use_container_width=True):
            qty = int(r['quantity'])
            db.run_sql("UPDATE redistribution_recommendations SET status='ACCEPTED' WHERE rec_id=:r", {"r": int(r['rec_id'])})
            db.run_sql("""INSERT INTO transfers (rec_id,status,agreed_price,agreed_quantity,
                          commission_rate,commission_amount,gross_value)
                          VALUES (:r,'ACCEPTED',:pr,:q,:cr,:ca,:gv)""",
                       {"r": int(r['rec_id']), "pr": float(r['suggested_price']), "q": qty,
                        "cr": COMMISSION_RATE, "ca": fee, "gv": gross})
            # --- move the stock: deduct from source batch, add a batch for the target ---
            src_batch = db.read_sql("""SELECT unit_cost, unit_price, manufacture_date, expiry_date, received_date
                                       FROM inventory_batches WHERE batch_id=:b""", {"b": int(r['batch_id'])})
            if not src_batch.empty:
                sb = src_batch.iloc[0]
                db.run_sql("UPDATE inventory_batches SET quantity = GREATEST(quantity - :q, 0) WHERE batch_id=:b",
                           {"q": qty, "b": int(r['batch_id'])})
                # target receives a new batch (same expiry; price = agreed price)
                db.run_sql("""INSERT INTO inventory_batches
                      (pharmacy_id, drug_id, quantity, unit_cost, unit_price,
                       manufacture_date, expiry_date, received_date, is_synthetic, is_expired)
                      VALUES (:p,:d,:q,:uc,:up,:mfg,:exp,CURRENT_DATE,FALSE,FALSE)""",
                      {"p": pick, "d": int(r['drug_id']), "q": qty,
                       "uc": float(sb["unit_cost"] or 0), "up": float(r['suggested_price']),
                       "mfg": sb["manufacture_date"], "exp": sb["expiry_date"]})
            if r['origin'] == 'REQUEST' and pd.notna(r.get('request_id')):
                db.run_sql("UPDATE stock_requests SET status='FULFILLED' WHERE request_id=:rq", {"rq": int(r['request_id'])})
            notify(r['other'], f"{pick} ACCEPTED your offer of {qty} units of {r['drug']} — stock transferred.", r['rec_id'])
            notify(pick, f"You accepted {r['other']}'s offer of {qty} units of {r['drug']} (fee ₦{fee:,.0f}).", r['rec_id'])
            st.toast("Transfer confirmed — stock moved."); st.rerun()
        if c3.button("Decline", key=f"rj{r['rec_id']}", use_container_width=True):
            db.run_sql("UPDATE redistribution_recommendations SET status='DECLINED' WHERE rec_id=:r", {"r": int(r['rec_id'])})
            notify(pick, f"You declined {r['other']}'s offer of {r['drug']}.", r['rec_id'])
            # try to re-match this surplus to a different pharmacy (exclude the one that declined)
            new_target = None
            if r['origin'] == 'SURPLUS' and pd.notna(r.get('batch_id')):
                try:
                    new_target = model3_matching.rematch_batch(int(r['batch_id']), exclude_pharmacies={pick, r['other']})
                except Exception:
                    new_target = None
            if new_target:
                notify(r['other'], f"{pick} declined your {r['drug']} offer — re-matched to {new_target}, ready to offer again.")
            else:
                notify(r['other'], f"{pick} declined your offer of {int(r['quantity'])} units of {r['drug']}.", r['rec_id'])
            st.rerun()

st.write("")
t1, t2, t3, t4, t5, t6, t7, t8, t9 = st.tabs(["At-risk stock", "To offer (surplus)", "Requests I can fulfil",
                                  "Offers to accept", "My requests", "My activity", "Expired stock", "Browse my stock",
                                  "📊 Dashboard"])

with t1:
    df = db.read_sql("""SELECT d.name AS drug, d.category, b.quantity, b.unit_price, b.expiry_date,
            ROUND(r.risk_probability::numeric,2) AS risk, r.risk_tier
        FROM expiry_risk_scores r JOIN inventory_batches b ON b.batch_id=r.batch_id
        JOIN drugs d ON d.drug_id=b.drug_id
        WHERE b.pharmacy_id=:p AND r.score_date=(SELECT MAX(score_date) FROM expiry_risk_scores) AND r.risk_tier IN ('High','Critical')
          AND b.expiry_date >= CURRENT_DATE + INTERVAL '3 days'
        ORDER BY r.risk_probability DESC""", {"p": pick})
    if df.empty:
        st.success("Nothing at risk right now.")
    else:
        df["expiry_date"] = pd.to_datetime(df["expiry_date"]); today = pd.Timestamp.today().normalize()
        def risk_phrase(p):
            if p >= 0.80: return "High probability of not clearing before expiry"
            if p >= 0.50: return "Moderate probability of not clearing before expiry"
            return "Some risk of not clearing before expiry"
        for _, r in df.iterrows():
            days = max((r["expiry_date"]-today).days, 0); value = float(r["quantity"])*float(r["unit_price"] or 0)
            cls = "red" if days<=7 else ("amber" if days<=21 else "green")
            mark = "●" if days<=7 else ("▲" if days<=21 else "■")
            phrase = risk_phrase(float(r["risk"]))
            st.markdown(f"""<div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
              <div><span class="drug">{r['drug']}</span><div class="meta">{r['category']} · {int(r['quantity'])} units · ₦{value:,.0f} at risk · {phrase}</div></div>
              <div style="text-align:right"><span class="pill t-{r['risk_tier']}">{r['risk_tier']}</span><br>
              <span class="chip {cls}" style="margin-top:6px;display:inline-block">{mark} {days} days left</span></div></div></div>""",
              unsafe_allow_html=True)

def _src_recs(origin):
    return db.read_sql("""SELECT rec.rec_id, rec.target_pharmacy_id AS other, d.name AS drug, rec.origin,
            rec.quantity, rec.suggested_price, ROUND(rec.match_score::numeric,2) AS score,
            ROUND(rec.distance_km::numeric,1) AS km, b.quantity AS available
        FROM redistribution_recommendations rec JOIN drugs d ON d.drug_id=rec.drug_id
        JOIN inventory_batches b ON b.batch_id=rec.batch_id
        WHERE rec.source_pharmacy_id=:p AND rec.status='RECOMMENDED' AND rec.origin=:o
        ORDER BY rec.match_score DESC""", {"p": pick, "o": origin})

with t2:
    recs = _src_recs("SURPLUS")
    if recs.empty: st.info("No surplus recommendations right now. Run the pipeline to refresh.")
    else:
        st.caption("Adjust then send the offer — the receiver confirms before any transfer is recorded.")
        for _, r in recs.iterrows(): offer_card(r, "s")

with t3:
    recs = _src_recs("REQUEST")
    if recs.empty: st.info("No requests you can fulfil right now.")
    else:
        st.caption("Another pharmacy requested stock you hold at risk — send an offer to fulfil it.")
        for _, r in recs.iterrows(): offer_card(r, "r")

with t4:
    offers = db.read_sql("""SELECT rec.rec_id, rec.source_pharmacy_id AS other, d.name AS drug, rec.origin,
            rec.request_id, rec.batch_id, rec.drug_id, rec.quantity, rec.suggested_price,
            ROUND(rec.match_score::numeric,2) AS score, ROUND(rec.distance_km::numeric,1) AS km
        FROM redistribution_recommendations rec JOIN drugs d ON d.drug_id=rec.drug_id
        WHERE rec.target_pharmacy_id=:p AND rec.status='OFFERED'
        ORDER BY rec.match_score DESC""", {"p": pick})
    if offers.empty: st.info("No offers awaiting your acceptance.")
    else:
        for _, r in offers.iterrows(): accept_card(r)

with t5:
    st.caption("Post what you need — the system auto-suggests a nearby pharmacy holding it at risk.")
    drugs = db.read_sql("SELECT drug_id, name, category FROM drugs ORDER BY name")
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2.5, 1, 1, 1], vertical_alignment="bottom")
        dsel = c1.selectbox("Drug needed", options=list(drugs["drug_id"]),
                            format_func=lambda i: drugs.set_index("drug_id").loc[i, "name"])
        qn = c2.number_input("Quantity", 1, value=50, step=1)
        mp = c3.number_input("Max ₦/unit (optional)", 0.0, value=0.0, step=10.0)
        if c4.button("Post request", type="primary", use_container_width=True):
            db.run_sql("""INSERT INTO stock_requests (pharmacy_id,drug_id,quantity_needed,max_price,status)
                          VALUES (:p,:d,:q,:mp,'OPEN')""",
                       {"p": pick, "d": int(dsel), "q": int(qn),
                        "mp": (None if mp == 0 else float(mp))})
            new_id = int(db.read_sql(
                "SELECT request_id FROM stock_requests WHERE pharmacy_id=:p "
                "ORDER BY created_at DESC, request_id DESC LIMIT 1",
                {"p": pick}).iloc[0]["request_id"])
            matched = requests_match.match_one(new_id)
            drug_name = drugs.set_index("drug_id").loc[int(dsel), "name"]
            notify(pick, f"You posted a request for {int(qn)} units of {drug_name}.")
            if matched:
                # find who it matched with to notify the requester (holder already notified in match_one)
                m = db.read_sql("""SELECT source_pharmacy_id FROM redistribution_recommendations
                                   WHERE request_id=:rq AND origin='REQUEST' ORDER BY rec_id DESC LIMIT 1""",
                                {"rq": new_id})
                if not m.empty:
                    notify(pick, f"Your request for {drug_name} was matched with {m.iloc[0]['source_pharmacy_id']}.", )
                st.toast("Request posted and matched to a nearby pharmacy.")
            else:
                st.toast("Request posted. No nearby at-risk match yet — it stays open.")
            st.rerun()
    mine = db.read_sql("""SELECT sr.request_id, d.name AS drug, sr.quantity_needed, sr.max_price, sr.status,
            rec.source_pharmacy_id AS matched_with, rec.quantity AS matched_qty,
            rec.suggested_price AS price, ROUND(rec.distance_km::numeric,1) AS km, rec.status AS offer_status
        FROM stock_requests sr JOIN drugs d ON d.drug_id=sr.drug_id
        LEFT JOIN redistribution_recommendations rec
               ON rec.request_id=sr.request_id AND rec.origin='REQUEST'
        WHERE sr.pharmacy_id=:p ORDER BY sr.created_at DESC""", {"p": pick})
    active = mine[mine["status"] != "CANCELLED"]
    cancelled = mine[mine["status"] == "CANCELLED"]
    if active.empty:
        st.caption("No active requests.")
    else:
        for _, r in active.iterrows():
            with st.container(border=True):
                if pd.notna(r["matched_with"]):
                    stage = {"RECOMMENDED": "awaiting their offer", "OFFERED": "offer sent — accept it under ‘Offers to accept’",
                             "ACCEPTED": "transfer confirmed", "DECLINED": "declined — will rematch"}.get(r["offer_status"], r["offer_status"])
                    cc1, cc2 = st.columns([5, 1], vertical_alignment="center")
                    cc1.markdown(
                        f"<div class='drug'>{r['drug']} <span class='pill b-REQUEST'>{r['status']}</span></div>"
                        f"<div class='meta'>Need {int(r['quantity_needed'])} · "
                        f"matched with <span class='route'>{r['matched_with']}</span> "
                        f"({int(r['matched_qty'])} units · {r['km']} km · ₦{r['price']:.0f}/unit) — {stage}</div>",
                        unsafe_allow_html=True)
                    # cancellable until the transfer is actually confirmed
                    if r["status"] not in ("CANCELLED", "FULFILLED") and r["offer_status"] != "ACCEPTED":
                        if cc2.button("Cancel", key=f"cx{int(r['request_id'])}", use_container_width=True):
                            notify(r["matched_with"], f"{pick} cancelled the request for {r['drug']} you were matched to fulfil.")
                            notify(pick, f"You cancelled your request for {r['drug']}.")
                            db.run_sql("""DELETE FROM notifications WHERE related_rec_id IN
                                          (SELECT rec_id FROM redistribution_recommendations
                                           WHERE request_id=:rq AND origin='REQUEST'
                                             AND status IN ('RECOMMENDED','OFFERED'))""", {"rq": int(r["request_id"])})
                            db.run_sql("""DELETE FROM redistribution_recommendations
                                          WHERE request_id=:rq AND origin='REQUEST' AND status IN ('RECOMMENDED','OFFERED')""",
                                       {"rq": int(r["request_id"])})
                            db.run_sql("UPDATE stock_requests SET status='CANCELLED' WHERE request_id=:rq", {"rq": int(r["request_id"])})
                            st.toast("Request cancelled."); st.rerun()
                else:
                    cc1, cc2 = st.columns([5, 1], vertical_alignment="center")
                    cc1.markdown(
                        f"<div class='drug'>{r['drug']} <span class='pill b-SURPLUS'>{r['status']}</span></div>"
                        f"<div class='meta'>Need {int(r['quantity_needed'])} units · "
                        f"{'cancelled' if r['status']=='CANCELLED' else 'no nearby at-risk match yet'}</div>",
                        unsafe_allow_html=True)
                    if r["status"] == "OPEN":
                        if cc2.button("Cancel", key=f"cx{int(r['request_id'])}", use_container_width=True):
                            db.run_sql("UPDATE stock_requests SET status='CANCELLED' WHERE request_id=:rq", {"rq": int(r["request_id"])})
                            notify(pick, f"You cancelled your request for {r['drug']}.")
                            st.toast("Request cancelled."); st.rerun()

    if not cancelled.empty:
        with st.expander(f"Cancelled requests ({len(cancelled)})"):
            for _, r in cancelled.iterrows():
                st.markdown(
                    f"<div class='meta'>{r['drug']} · need {int(r['quantity_needed'])} units · "
                    f"<span style='color:var(--crit)'>cancelled</span></div>",
                    unsafe_allow_html=True)

with t6:
    st.caption("Every offer and transfer you're involved in, with its current status.")
    acts = db.read_sql("""
        SELECT rec.rec_id, d.name AS drug, rec.quantity, rec.suggested_price,
               rec.source_pharmacy_id AS src, rec.target_pharmacy_id AS tgt,
               rec.origin, rec.status AS rec_status,
               t.status AS transfer_status, t.commission_amount, t.gross_value
        FROM redistribution_recommendations rec
        JOIN drugs d ON d.drug_id=rec.drug_id
        LEFT JOIN transfers t ON t.rec_id=rec.rec_id
        WHERE (rec.source_pharmacy_id=:p OR rec.target_pharmacy_id=:p)
          AND rec.status IN ('OFFERED','ACCEPTED','DECLINED')
        ORDER BY rec.rec_id DESC
    """, {"p": pick})
    if acts.empty:
        st.info("No activity yet. Send or accept an offer and it will appear here.")
    else:
        # derive a friendly status + role
        def status_label(r):
            if r["rec_status"] == "DECLINED": return "Declined", "red"
            if r["rec_status"] == "ACCEPTED": return "Completed", "green"
            if r["rec_status"] == "OFFERED":  return "Sent (pending)", "amber"
            return r["rec_status"], "amber"
        for _, r in acts.iterrows():
            role = "Sent to" if r["src"] == pick else "Received from"
            other = r["tgt"] if r["src"] == pick else r["src"]
            label, cls = status_label(r)
            fee = f" · fee ₦{float(r['commission_amount']):,.0f}" if pd.notna(r["commission_amount"]) else ""
            st.markdown(f"""<div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div><span class="drug">{r['drug']}</span>
                  <div class="meta">{role} <span class='route'>{other}</span> · {int(r['quantity'])} units · ₦{float(r['suggested_price']):.0f}/unit{fee}</div></div>
                <span class="chip {cls}">{label}</span></div></div>""", unsafe_allow_html=True)

with t7:
    st.caption("Stock that lapsed before it could be sold or redistributed — the waste registry.")
    exp = db.read_sql("""SELECT d.name AS drug, d.category, e.units_expired, e.unit_cost,
                                e.value_lost, e.expiry_date, e.logged_at
                         FROM expired_stock e JOIN drugs d ON d.drug_id=e.drug_id
                         WHERE e.pharmacy_id=:p ORDER BY e.expiry_date DESC""", {"p": pick})
    if exp.empty:
        st.success("No expired stock recorded. Nothing has been lost to expiry.")
    else:
        total = float(exp["value_lost"].sum())
        st.markdown(f"<div class='kpi crit' style='max-width:280px'><div class='v'>₦{total:,.0f}</div>"
                    f"<div class='l'>Total value lost to expiry</div></div>", unsafe_allow_html=True)
        st.write("")
        st.dataframe(exp, use_container_width=True, hide_index=True)

with t8:
    stock = db.read_sql("""SELECT d.name AS drug, d.category, b.quantity, b.unit_price, b.expiry_date
        FROM inventory_batches b JOIN drugs d ON d.drug_id=b.drug_id
        WHERE b.pharmacy_id=:p AND b.is_expired=FALSE AND b.quantity>0 ORDER BY b.expiry_date""", {"p": pick})
    if stock.empty: st.info("No stock recorded.")
    else:
        st.dataframe(stock, use_container_width=True, hide_index=True)
        ink = "#EEF4F1" if dark else "#16302B"; brand = "#3BB89C" if dark else "#0F6E5C"
        by_cat = stock.groupby("category", as_index=False)["quantity"].sum()
        fig = px.bar(by_cat, x="category", y="quantity", title="Stock by category")
        fig.update_traces(marker_color=brand)
        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          font_color=ink, title_font_family="Fraunces", xaxis_title=None, yaxis_title="Units", bargap=0.35)
        st.plotly_chart(fig, use_container_width=True)

with t9:
    st.caption("A live snapshot of your pharmacy. These figures update automatically after every action.")
    m = dashboard.metrics(pick)
    ink = "#EEF4F1" if dark else "#16302B"; brand = "#3BB89C" if dark else "#0F6E5C"

    # headline KPI cards
    st.markdown(f"""
    <div class="kpis">
      <div class="kpi"><div class="v">₦{m['stock_value']:,.0f}</div><div class="l">Total stock value</div></div>
      <div class="kpi {'crit' if m['at_risk_value']>0 else ''}"><div class="v">₦{m['at_risk_value']:,.0f}</div><div class="l">Value at risk of expiry</div></div>
      <div class="kpi"><div class="v">₦{m['value_sold']:,.0f}</div><div class="l">Value redistributed</div></div>
      <div class="kpi {'crit' if m['waste_value']>0 else ''}"><div class="v">₦{m['waste_value']:,.0f}</div><div class="l">Value lost to expiry</div></div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(f"""
    <div class="kpis">
      <div class="kpi"><div class="v">{m['batches']:,}</div><div class="l">Batches in stock</div></div>
      <div class="kpi"><div class="v">{m['at_risk_batches']:,}</div><div class="l">Batches at risk</div></div>
      <div class="kpi"><div class="v">{m['transfers']:,}</div><div class="l">Completed transfers</div></div>
      <div class="kpi"><div class="v">{(str(round(m['rescue_ratio']*100))+'%') if m['rescue_ratio'] is not None else '—'}</div><div class="l">Operational rescue ratio</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.write("")
    cda, cdb = st.columns(2)
    with cda:
        if m["top_sellers"].empty:
            st.info("No sales in the last 90 days to rank best-sellers.")
        else:
            ts = m["top_sellers"].sort_values("units")
            fig = px.bar(ts, x="units", y="drug", orientation="h", title="Top 5 best-selling drugs (90 days)")
            fig.update_traces(marker_color=brand)
            fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                              font_color=ink, title_font_family="Fraunces", xaxis_title="Units sold",
                              yaxis_title=None, bargap=0.3, height=320, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
    with cdb:
        if m["by_category"].empty:
            st.info("No stock to break down by category.")
        else:
            fig2 = px.pie(m["by_category"], names="category", values="value", title="Stock value by category", hole=0.55)
            fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               font_color=ink, title_font_family="Fraunces", height=320, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.markdown("**Download or email report**")
    st.caption("Pick the date range for page 1 of the report. Page 2 is always the full all-time summary.")
    try:
        today = pd.Timestamp.today().normalize()
        month_start = today.replace(day=1)
        rc1, rc2 = st.columns(2)
        d_from = rc1.date_input("From", value=month_start.date(), key="rep_from")
        d_to = rc2.date_input("To", value=today.date(), key="rep_to")

        if d_from > d_to:
            st.warning("‘From’ date must be on or before ‘To’ date.")
        else:
            # label e.g. "01 Jun – 30 Jun 2026"; period end is exclusive (add a day)
            start = pd.Timestamp(d_from).to_pydatetime()
            end = (pd.Timestamp(d_to) + pd.Timedelta(days=1)).to_pydatetime()
            range_label = f"{d_from:%d %b %Y} – {d_to:%d %b %Y}"
            pdf_bytes = dashboard.build_pdf(pick, f"{pick} · {me['area']}",
                                            period=(start, end, range_label))
            fname = f"MedShare_{pick}_{d_from:%Y%m%d}-{d_to:%Y%m%d}.pdf"

            dc1, dc2, dc3 = st.columns([1.1, 1.6, 1.1], vertical_alignment="bottom")
            with dc1:
                st.download_button("⬇ Download PDF", data=pdf_bytes, file_name=fname,
                                   mime="application/pdf", type="primary", use_container_width=True)
            saved_email = db.read_sql("SELECT email FROM pharmacies WHERE pharmacy_id=:p", {"p": pick}).iloc[0]["email"]
            with dc2:
                to_email = st.text_input("Send to email", value=(saved_email or ""), key="rep_email",
                                         placeholder="pharmacy@example.com", label_visibility="collapsed")
            with dc3:
                if st.button("✉ Email report", use_container_width=True):
                    from src import emailer
                    if not to_email:
                        st.warning("Enter an email address first.")
                    elif not emailer.is_configured():
                        st.warning("Email isn't set up yet. Add the SMTP secrets to enable sending.")
                    else:
                        try:
                            plain, html = emailer.report_email_body(pick, me['area'], range_label)
                            emailer.send_report(
                                to_email, f"MedShare report — {pick} ({range_label})",
                                plain, pdf_bytes, fname, body_html=html)
                            db.run_sql("UPDATE pharmacies SET email=:e WHERE pharmacy_id=:p",
                                       {"e": to_email, "p": pick})
                            st.success(f"Report sent to {to_email}.")
                        except Exception as ex:
                            st.error(f"Could not send: {ex}")
    except Exception as e:
        st.warning("PDF generation needs the reportlab package. Add `reportlab` to requirements.txt and reboot the app.")