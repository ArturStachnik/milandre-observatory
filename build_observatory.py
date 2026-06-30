"""Daily observatory build for Milamont (BAFU 6748, Boncourt - Milandre Amont).

One canonical hourly file and one canonical 5-minute file, both updated in place
(upsert + atomic write), never one-file-per-day. The hourly file is shipped
pre-seeded with history (one combined file built by make_seed.py) and then grows
with the live observed feed. The operational job needs no other inputs.

Hourly schema:   datetime_utc, q_l_s, q_source, level_m, water_temp_c,
                 conductivity_us_cm, turbidity_ntu, p_mm_h, t_air_c
5-minute schema: datetime_utc, q_obs_l_s, level_m, water_temp_c,
                 conductivity_us_cm, turbidity_ntu, p_mm_h, t_air_c
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import config
import store
from fetch_bafu import fetch_bafu_5min
from fetch_fahy import fetch_fahy_hourly

log = logging.getLogger("observatory")

HOURLY_COLS = ["datetime_utc", "q_l_s", "q_source", "level_m", "water_temp_c",
               "conductivity_us_cm", "turbidity_ntu", "p_mm_h", "t_air_c"]
BAFU_MEAN = ["q_obs_l_s", "level_m", "water_temp_c", "conductivity_us_cm", "turbidity_ntu"]


def _bafu_to_hourly(bafu5: pd.DataFrame) -> pd.DataFrame:
    if bafu5.empty:
        return pd.DataFrame(columns=["datetime_utc"])
    s = bafu5.set_index("datetime_utc").sort_index()
    cols = [c for c in BAFU_MEAN if c in s.columns]
    return s[cols].resample("1h").mean().reset_index()


def run() -> None:
    if not config.HOURLY_CSV.exists():
        log.warning("no seed at %s; the hourly record will start from live data only. "
                    "Place the combined seed (make_seed.py) to include history.",
                    config.HOURLY_CSV)

    bafu5 = fetch_bafu_5min()
    fahy = fetch_fahy_hourly()

    # 5-minute canonical: BAFU at native cadence, Fahy placed at its exact hour
    # (null between hours, never fabricated).
    if not bafu5.empty:
        hi = bafu5.merge(fahy, on="datetime_utc", how="left") if not fahy.empty else bafu5
        store.upsert(config.HIGHRES_CSV, hi)

    # hourly canonical: BAFU averaged to the hour + Fahy, observed discharge wins.
    bafu_h = _bafu_to_hourly(bafu5)
    if not bafu_h.empty or not fahy.empty:
        if not bafu_h.empty and not fahy.empty:
            h = pd.merge(bafu_h, fahy, on="datetime_utc", how="outer")
        else:
            h = bafu_h if not bafu_h.empty else fahy.copy()
        if "q_obs_l_s" in h.columns:
            h["q_l_s"] = h["q_obs_l_s"]
            h["q_source"] = np.where(h["q_obs_l_s"].notna(), "obs", None)
        keep = [c for c in HOURLY_COLS if c in h.columns]
        store.upsert(config.HOURLY_CSV, h[keep])

    log.info("observatory update complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    run()
