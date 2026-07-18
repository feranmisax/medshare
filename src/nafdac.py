"""
NAFDAC validation-only integration (Chapter 3, §3.1.4).

Design decision (see thesis): the drug catalogue is DRAWN FROM the survey and
VALIDATED AGAINST the NAFDAC Green Book — NAFDAC is a validation cross-check, not
a bulk data source. The Green Book cannot be bulk-downloaded, so this module does
NOT scrape anything. Instead it reads an OPTIONAL, curated snapshot file that the
researcher exports/copies once (the ~40-50 catalogue drugs), if it exists.

Behaviour:
  * If data/nafdac_catalogue.csv is ABSENT  -> functions are no-ops; the pipeline
    runs exactly as before (no new dependency, fully reproducible offline).
  * If it is PRESENT -> the catalogue is annotated with a `nafdac_validated` flag
    and (where available) a registration number, and a short report is printed.

Expected CSV columns (case-insensitive, extra columns ignored):
    drug_name , nafdac_reg_no (optional) , form (optional)

This keeps the methodology's NAFDAC claim truthful without making the thesis run
depend on an external website.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import re
import pandas as pd
import config


def _norm(name: str) -> str:
    """Loose normalisation for name matching (lowercase, strip dosage/form/punct)."""
    n = re.sub(r"\s+", " ", str(name)).strip().lower()
    n = re.sub(r"\d+\s*(mg|mcg|g|ml|iu|%).*$", "", n)
    n = re.sub(r"\b(tab|tabs|tablet|tablets|cap|caps|capsule|syrup|syr|suspension|injection|inj)\b",
               "", n)
    n = re.sub(r"[^a-z ]+", "", n).strip()
    return n


def available() -> bool:
    """True if a curated NAFDAC snapshot file is present."""
    return config.NAFDAC_CATALOGUE_FILE.exists()


def load_reference() -> pd.DataFrame | None:
    """Load the curated NAFDAC snapshot, or None if it is absent/unreadable."""
    if not available():
        return None
    try:
        ref = pd.read_csv(config.NAFDAC_CATALOGUE_FILE)
    except Exception as e:                                   # noqa: BLE001
        print(f"[nafdac] could not read {config.NAFDAC_CATALOGUE_FILE.name}: {e}")
        return None
    ref.columns = [c.strip().lower() for c in ref.columns]
    if "drug_name" not in ref.columns:
        print("[nafdac] snapshot has no 'drug_name' column; skipping validation.")
        return None
    ref["_key"] = ref["drug_name"].map(_norm)
    return ref


def validate_catalogue(catalogue: pd.DataFrame) -> pd.DataFrame:
    """Annotate the survey-derived catalogue with NAFDAC validation results.

    Adds a boolean column `nafdac_validated` and, if present in the snapshot, a
    `nafdac_reg_no` column. If no snapshot exists, the catalogue is returned
    unchanged (with nafdac_validated = pd.NA) so downstream code is agnostic.
    """
    cat = catalogue.copy()
    ref = load_reference()
    if ref is None:
        cat["nafdac_validated"] = pd.NA          # unknown — validation not run
        return cat

    ref_keys = set(ref["_key"])
    reg_lookup = (ref.dropna(subset=["nafdac_reg_no"]).set_index("_key")["nafdac_reg_no"].to_dict()
                  if "nafdac_reg_no" in ref.columns else {})

    keys = cat["name"].map(_norm)
    cat["nafdac_validated"] = keys.isin(ref_keys)
    if reg_lookup:
        cat["nafdac_reg_no"] = keys.map(reg_lookup)

    n_ok = int(cat["nafdac_validated"].sum())
    n_tot = len(cat)
    print(f"[nafdac] validated {n_ok}/{n_tot} catalogue drugs against the Green Book snapshot.")
    missing = cat.loc[~cat["nafdac_validated"], "name"].tolist()
    if missing:
        print(f"[nafdac] not found in snapshot (verify manually): {', '.join(missing[:12])}"
              + (" ..." if len(missing) > 12 else ""))
    return cat


if __name__ == "__main__":
    if not available():
        print(f"No NAFDAC snapshot at {config.NAFDAC_CATALOGUE_FILE} — validation is optional and skipped.")
    else:
        ref = load_reference()
        print(f"Loaded {0 if ref is None else len(ref)} NAFDAC reference rows.")
