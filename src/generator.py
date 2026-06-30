"""
Calibrated, hybrid (real + synthetic) data generator.

Reads the cleaned survey files in data/ and builds a ~150-pharmacy network
with daily sales series and batch-level inventory, then loads it into Postgres.

The 39 REAL survey pharmacies are kept as anchors; the remaining pharmacies are
synthetic, drawn to match the survey's marginals (type mix, category mix,
demand levels, prices, expiry propensity, willingness, geography).

Run:  python -m src.generator
"""
import sys, math, re
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import config
from src import db

RNG = np.random.default_rng(config.RANDOM_SEED)

# Approximate coordinates of Lagos areas (lat, lon) for plausible geography.
AREA_COORDS = {
    "Ikeja": (6.6018, 3.3515), "Ogba": (6.6307, 3.3417), "Lekki": (6.4413, 3.5095),
    "Victoria Island": (6.4281, 3.4219), "Surulere": (6.4969, 3.3540),
    "Yaba": (6.5095, 3.3711), "Alimosho": (6.5950, 3.2700), "Alagbado": (6.6680, 3.2740),
    "Egbeda": (6.6050, 3.2860), "Ikoyi": (6.4520, 3.4350), "Abule Egba": (6.6450, 3.3050),
    "Abuleegba": (6.6450, 3.3050), "Ifako-Ijaiye": (6.6700, 3.3200), "Akute": (6.7100, 3.3300),
    "Lagos Island": (6.4550, 3.3940), "Ejigbo": (6.5470, 3.2980), "Amuwo Odofin": (6.4660, 3.2780),
    "Badagry": (6.4150, 2.8810), "Ojo": (6.4600, 3.1700), "Opebi": (6.5900, 3.3600),
    "Fagba": (6.6500, 3.3300), "Alakuko": (6.6800, 3.2600), "Oja Oba": (6.6450, 3.3050),
}
LAGOS_CENTER = (6.5244, 3.3792)
CATEGORIES = ["Antibiotics","Antimalarials","Analgesics","Antihypertensives",
              "Antidiabetics","Antacids/GI","Vitamins/Supplements","Cough/Cold"]
# Relative expiry propensity per category (slow movers expire more). Calibrated
# from the survey's expired-item evidence + conservative literature assumptions.
EXPIRY_PROPENSITY = {
    "Antibiotics":0.9,"Antimalarials":0.8,"Analgesics":0.5,"Antihypertensives":1.1,
    "Antidiabetics":1.2,"Antacids/GI":0.9,"Vitamins/Supplements":1.0,"Cough/Cold":0.7,
}


def _coords_for_area(area):
    base = AREA_COORDS.get(str(area).title(), LAGOS_CENTER)
    return (base[0] + RNG.normal(0, 0.01), base[1] + RNG.normal(0, 0.01))


def load_survey():
    sc = pd.read_excel(config.DATA_DIR / "survey_clean.xlsx")
    drugs = pd.read_excel(config.DATA_DIR / "drugs_long.xlsx")
    return sc, drugs


def build_drug_catalogue(drugs_long):
    """Build a CLEAN catalogue from messy survey free-text: normalise names,
    drop junk/list-blobs, map to categories, and de-duplicate case-insensitively."""
    name_to_cat = {
        "amoxicillin":"Antibiotics","ampiclox":"Antibiotics","ampiclox":"Antibiotics",
        "ciprofloxacin":"Antibiotics","ciprotab":"Antibiotics","azithromycin":"Antibiotics",
        "clarithromycin":"Antibiotics","levofloxacin":"Antibiotics","amoxiclav":"Antibiotics",
        "metronidazole":"Antacids/GI","omeprazole":"Antacids/GI","antacid":"Antacids/GI",
        "artemether":"Antimalarials","lonart":"Antimalarials","amatem":"Antimalarials",
        "act":"Antimalarials","coartem":"Antimalarials","quinine":"Antimalarials",
        "sulphadoxine":"Antimalarials","artether":"Antimalarials",
        "paracetamol":"Analgesics","pcm":"Analgesics","ibuprofen":"Analgesics",
        "diclofenac":"Analgesics","analgesic":"Analgesics",
        "amlodipine":"Antihypertensives","amlopine":"Antihypertensives","lisinopril":"Antihypertensives",
        "losartan":"Antihypertensives","valsartan":"Antihypertensives","exforge":"Antihypertensives",
        "methyldopa":"Antihypertensives","bisoprolol":"Antihypertensives",
        "metformin":"Antidiabetics","glibenclamide":"Antidiabetics","glipizide":"Antidiabetics",
        "vitamin":"Vitamins/Supplements","multivitamin":"Vitamins/Supplements",
        "folic":"Vitamins/Supplements","blood tonic":"Vitamins/Supplements","obron":"Vitamins/Supplements",
        "supplement":"Vitamins/Supplements","cod liver":"Vitamins/Supplements",
        "cough":"Cough/Cold","loratadine":"Cough/Cold","loratidine":"Cough/Cold",
        "cetirizine":"Cough/Cold","piriton":"Cough/Cold","chlorpheniramine":"Cough/Cold",
    }
    # canonical display names for common variants (collapse spelling/dosage noise)
    canon = {
        "pcm":"Paracetamol","amlopine":"Amlodipine","loratidine":"Loratadine",
        "ciprotab":"Ciprofloxacin","amatem":"Artemether/Lumefantrine",
        "lonart":"Artemether/Lumefantrine","coartem":"Artemether/Lumefantrine",
        "act":"Artemether/Lumefantrine","artemether":"Artemether/Lumefantrine",
        "cough":"Cough Syrup","blood tonic":"Blood Tonic","metformine":"Metformin",
        "multivitamin":"Multivitamins","amlodipine":"Amlodipine","amoxicillin":"Amoxicillin",
        "paracetamol":"Paracetamol","ibuprofen":"Ibuprofen","vitamin c":"Vitamin C",
        "vitamin d":"Vitamin D","omeprazole":"Omeprazole","metronidazole":"Metronidazole",
    }

    def clean_name(raw):
        n = re.sub(r"\s+", " ", str(raw)).strip()
        n = re.sub(r"^\d+[\.\)]\s*", "", n)                       # leading list numbering
        # strip dosage-form prefixes (tab/cap/iv/im/syr/inj/oral ...)
        n = re.sub(r"^(tab|tabs|cap|caps|capsule|iv|im|inj|injection|syr|syrup|oral|soft\s*gel)\b\.?\s*",
                   "", n, flags=re.I)
        n = re.sub(r"\d+\s*(mg|mcg|g|ml|iu|%).*$", "", n, flags=re.I)   # trailing dosage/price
        n = re.sub(r"[#:;\-/\.,]+$", "", n).strip()               # trailing punctuation
        n = re.sub(r"\b(tab|tabs|tablet|tablets|syr|syrup|syrups|caps?|suspension)\b\.?$",
                   "", n, flags=re.I).strip()                     # trailing form words
        return n

    def is_junk(n):
        low = n.lower()
        if len(n) < 3 or len(n) > 40:
            return True
        if n.count(",") >= 1:
            return True
        if not re.search(r"[a-zA-Z]", n):
            return True
        bad = ["can't recall", "cant recall", "lot to list", "this is", "n/a", "na",
               "free", "infusion", "normal saline", "this is a"]
        return any(b in low for b in bad)

    def categorise(name):
        n = str(name).lower()
        for k, c in name_to_cat.items():
            if k in n:
                return c
        return None                              # unknown -> drop rather than random-assign

    rows, seen = [], set()
    for raw in drugs_long["drug_name"].dropna().unique():
        nm = clean_name(raw)
        if is_junk(nm):
            continue
        cat = categorise(nm)
        if cat is None:
            continue
        # apply canonical name where a known variant matches
        display = nm.title()
        for key, cn in canon.items():
            if key in nm.lower():
                display = cn
                break
        dedupe_key = display.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append({"name": display, "category": cat, "pack_size": 1, "unit": "unit"})

    for c in CATEGORIES:                          # ensure every category has a generic item
        gname = f"Generic {c.split('/')[0]}"
        if gname.lower() not in seen:
            seen.add(gname.lower())
            rows.append({"name": gname, "category": c, "pack_size": 1, "unit": "unit"})

    cat = pd.DataFrame(rows).drop_duplicates(subset=["name"]).reset_index(drop=True)
    return cat


def make_pharmacies(survey):
    """39 real anchors + synthetic pharmacies to reach N_PHARMACIES."""
    real = survey.copy()
    real["is_synthetic"] = False
    real = real.rename(columns={})
    for _, r in real.iterrows():
        pass
    real_rows = []
    for _, r in real.iterrows():
        lat, lon = _coords_for_area(r["area"])
        real_rows.append(dict(
            pharmacy_id=r["pharmacy_id"], name=f"Pharmacy {r['pharmacy_id']}",
            pharmacy_type=r["pharmacy_type"], area=r["area"], landmark=r.get("landmark"),
            latitude=lat, longitude=lon, willing_receive=r.get("willing_receive"),
            willing_release=r.get("willing_release"), travel_km_max=r.get("travel_km_max"),
            is_synthetic=False,
        ))
    # marginals for synthetic draws
    type_p = survey["pharmacy_type"].value_counts(normalize=True)
    areas = list(AREA_COORDS.keys())
    recv_p = survey["willing_receive"].value_counts(normalize=True)
    rel_p = survey["willing_release"].value_counts(normalize=True)
    travel_vals = survey["travel_km_max"].dropna().values

    n_syn = max(0, config.N_PHARMACIES - len(real_rows))
    syn_rows = []
    for i in range(n_syn):
        pid = f"SY{i+1:04d}"
        area = RNG.choice(areas)
        lat, lon = _coords_for_area(area)
        syn_rows.append(dict(
            pharmacy_id=pid, name=f"Pharmacy {pid}",
            pharmacy_type=RNG.choice(type_p.index, p=type_p.values),
            area=area, landmark=None, latitude=lat, longitude=lon,
            willing_receive=RNG.choice(recv_p.index, p=recv_p.values),
            willing_release=RNG.choice(rel_p.index, p=rel_p.values),
            travel_km_max=float(RNG.choice(travel_vals)) if len(travel_vals) else 8.0,
            is_synthetic=True,
        ))
    return pd.DataFrame(real_rows + syn_rows)


def make_sales_and_batches(pharmacies, catalogue, drugs_long):
    """Generate daily sales (negative-binomial) and inventory batches per pharmacy-drug."""
    # demand level priors from survey (units/week), per category
    dl = drugs_long.dropna(subset=["units_per_week"]).copy()
    price_by_cat, demand_by_cat = {}, {}
    # crude category attach for priors
    for c in CATEGORIES:
        demand_by_cat[c] = dl["units_per_week"].median() if len(dl) else 40.0
        price_by_cat[c] = drugs_long["unit_price_naira"].dropna().median() if drugs_long["unit_price_naira"].notna().any() else 650.0

    cat_drug_ids = {c: catalogue.index[catalogue["category"] == c].tolist() for c in CATEGORIES}
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=config.SIM_DAYS - 1)
    dates = pd.date_range(start, end, freq="D")
    # seasonal index: mild antimalarial uplift mid-year (rainy season proxy)
    doy = dates.dayofyear.values
    season = 1.0 + 0.15 * np.sin(2 * np.pi * (doy - 120) / 365.0)

    sales_rows, batch_rows = [], []
    for _, ph in pharmacies.iterrows():
        # each pharmacy stocks 4-8 categories
        n_cat = RNG.integers(4, 9)
        chosen = RNG.choice(CATEGORIES, size=min(n_cat, len(CATEGORIES)), replace=False)
        scale = {"Independent":1.0,"Hospital/Clinic":1.6,"Small chain":1.3,"Large chain":2.0}.get(ph["pharmacy_type"], 1.0)
        for c in chosen:
            if not cat_drug_ids[c]:
                continue
            did = int(RNG.choice(cat_drug_ids[c]))   # catalogue row index == drug_id-1 later
            weekly = max(1.0, demand_by_cat[c] * scale * RNG.uniform(0.4, 1.6))
            daily_mu = weekly / 7.0
            # intermittency: slower movers get more zero-days
            p_zero = float(np.clip(0.05 + 0.25 * (EXPIRY_PROPENSITY[c] - 0.5), 0.0, 0.6))
            # negative-binomial via gamma-poisson
            r_disp = 4.0
            for k, d in enumerate(dates):
                if RNG.random() < p_zero:
                    units = 0
                else:
                    lam = daily_mu * season[k] * RNG.gamma(r_disp, 1.0 / r_disp)
                    units = int(RNG.poisson(max(lam, 0.01)))
                sales_rows.append((ph["pharmacy_id"], did, d.date(), units))
            # inventory: 1-2 batches with realistic expiry windows
            price = max(10.0, price_by_cat[c] * RNG.uniform(0.6, 1.5))
            cost = price * RNG.uniform(0.55, 0.8)
            for _b in range(int(RNG.integers(1, 3))):
                shelf_days = int(RNG.integers(60, 540))
                received = end - pd.Timedelta(days=int(RNG.integers(0, 120)))
                manufacture = received - pd.Timedelta(days=int(RNG.integers(30, 200)))
                expiry = received + pd.Timedelta(days=shelf_days)
                # quantity scaled to demand and propensity (overstock for expiry-prone)
                qty = int(max(5, weekly * RNG.uniform(2, 8) * EXPIRY_PROPENSITY[c]))
                batch_rows.append(dict(
                    pharmacy_id=ph["pharmacy_id"], drug_id=did, quantity=qty,
                    unit_cost=round(cost, 2), unit_price=round(price, 2),
                    manufacture_date=manufacture.date(), expiry_date=expiry.date(),
                    received_date=received.date(),
                    is_synthetic=bool(ph["is_synthetic"]),
                ))
    sales = pd.DataFrame(sales_rows, columns=["pharmacy_id","drug_id","sale_date","units_sold"])
    batches = pd.DataFrame(batch_rows)
    return sales, batches


def main():
    if not db.ping():
        print("Cannot reach the database. Check DATABASE_URL in .env and that Postgres is running.")
        return
    print("Loading cleaned survey ...")
    survey, drugs_long = load_survey()

    print("Building drug catalogue ...")
    catalogue = build_drug_catalogue(drugs_long)
    # clear & load drugs; drug_id will be assigned 1..N in insertion order
    db.run_sql("TRUNCATE drugs RESTART IDENTITY CASCADE;")
    db.write_df(catalogue.assign(), "drugs")
    cat_db = db.read_sql("SELECT drug_id, name, category FROM drugs ORDER BY drug_id")
    # map our 0-based catalogue index -> real drug_id
    idx_to_id = {i: int(cat_db.iloc[i]["drug_id"]) for i in range(len(cat_db))}

    print("Creating pharmacies ...")
    pharmacies = make_pharmacies(survey)
    db.run_sql("TRUNCATE pharmacies CASCADE;")
    db.write_df(pharmacies, "pharmacies")

    print(f"Generating {config.SIM_DAYS} days of sales + batches for {len(pharmacies)} pharmacies ...")
    sales, batches = make_sales_and_batches(pharmacies, catalogue, drugs_long)
    sales["drug_id"] = sales["drug_id"].map(idx_to_id)
    batches["drug_id"] = batches["drug_id"].map(idx_to_id)

    print(f"Loading {len(sales):,} sales rows and {len(batches):,} batches ...")
    db.write_df(sales, "sales_daily")
    db.write_df(batches, "inventory_batches")

    print("Done. Summary:")
    print(db.read_sql("""
        SELECT (SELECT COUNT(*) FROM pharmacies) AS pharmacies,
               (SELECT COUNT(*) FROM drugs) AS drugs,
               (SELECT COUNT(*) FROM inventory_batches) AS batches,
               (SELECT COUNT(*) FROM sales_daily) AS sales_rows
    """).to_string(index=False))


if __name__ == "__main__":
    main()
