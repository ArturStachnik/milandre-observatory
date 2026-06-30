"""Build the single combined seed for the observatory (run once).

Merges the Milamont reconstruction and the historical Fahy record into one
hourly file with the observatory schema. The daily job does not use this; it
only grows the file produced here. Kept in the repo to document, and let anyone
reproduce, how the historical backbone was derived.

Usage:
    python make_seed.py reconstruction.csv master.csv [out.csv]

reconstruction.csv : datetime_utc, q_obs, q_rec, bf_rec, qf_rec
master.csv         : must contain datetime_utc, q_l_s, p_mm_h, t_c
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import config

HOURLY_COLS = ["datetime_utc", "q_l_s", "q_source", "level_m", "water_temp_c",
               "conductivity_us_cm", "turbidity_ntu", "p_mm_h", "t_air_c"]


def build_seed(recon_path: str, master_path: str) -> pd.DataFrame:
    recon = pd.read_csv(recon_path)
    recon["datetime_utc"] = pd.to_datetime(recon["datetime_utc"])
    master = pd.read_csv(master_path, usecols=["datetime_utc", "q_l_s", "p_mm_h", "t_c"])
    master["datetime_utc"] = pd.to_datetime(master["datetime_utc"])
    master = master.rename(columns={"t_c": "t_air_c"})

    df = pd.merge(recon, master, on="datetime_utc", how="outer").sort_values("datetime_utc")

    q_obs = df["q_obs"] if "q_obs" in df else pd.Series(np.nan, index=df.index)
    if "q_l_s" in df:                                   # master observed as a fallback source
        q_obs = q_obs.where(q_obs.notna(), df["q_l_s"])
    q_rec = df["q_rec"] if "q_rec" in df else pd.Series(np.nan, index=df.index)

    df["q_l_s"] = q_obs.where(q_obs.notna(), q_rec)
    df["q_source"] = np.where(q_obs.notna(), "obs",
                              np.where(q_rec.notna(), "recon", None))
    for c in ["level_m", "water_temp_c", "conductivity_us_cm", "turbidity_ntu"]:
        df[c] = pd.NA
    return df.reindex(columns=HOURLY_COLS)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    recon_path, master_path = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else str(config.HOURLY_CSV)
    seed = build_seed(recon_path, master_path)
    seed.to_csv(out, index=False)
    print(f"wrote {len(seed):,} rows -> {out}")
    print(f"range: {seed['datetime_utc'].min()} -> {seed['datetime_utc'].max()}")
    print(seed["q_source"].value_counts(dropna=False).to_string())
