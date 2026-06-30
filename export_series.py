"""Build the /series overview JSON (discharge + precipitation) from the hourly
observatory file, decimated to 6-hourly windows, in the schema the website's
time-series viewer consumes.

Schema produced:
    label, t_start_utc, step_h, n, var_name, var_units,
    values (observed discharge, null where reconstructed),
    recon  (reconstructed discharge, null where observed),
    secondary {name, units, reversed, values}  (precipitation),
    note
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

import config

log = logging.getLogger("export_series")


def _nullsafe(seq):
    return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else v for v in seq]


def build_series_json() -> dict:
    df = pd.read_csv(config.HOURLY_CSV)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"])
    df = df.sort_values("datetime_utc").set_index("datetime_utc")

    step = f"{config.SERIES_STEP_H}h"
    obs = df["q_l_s"].where(df["q_source"] == "obs")
    rec = df["q_l_s"].where(df["q_source"] == "recon")

    values = obs.resample(step).mean().round(2)
    recon = rec.resample(step).mean().round(2).reindex(values.index)
    precip = df["p_mm_h"].resample(step).mean().round(1).reindex(values.index)

    # trim leading windows that carry no discharge at all
    has_q = values.notna() | recon.notna()
    if has_q.any():
        first = has_q.idxmax()
        values, recon, precip = values.loc[first:], recon.loc[first:], precip.loc[first:]

    grid = values.index
    return {
        "label": config.SERIES_LABEL,
        "t_start_utc": grid[0].strftime("%Y-%m-%d %H:%M:%S"),
        "step_h": config.SERIES_STEP_H,
        "n": int(len(grid)),
        "var_name": "Discharge",
        "var_units": "L/s",
        "values": _nullsafe(values.tolist()),
        "recon": _nullsafe(recon.tolist()),
        "secondary": {
            "name": "Precipitation",
            "units": "mm/h",
            "reversed": True,
            "values": _nullsafe(precip.tolist()),
        },
        "note": f"Overview decimated to {config.SERIES_STEP_H}-hourly windows.",
    }


def run() -> None:
    payload = build_series_json()
    tmp = f"{config.SERIES_JSON}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, config.SERIES_JSON)
    log.info("wrote /series overview: n=%d, start=%s -> %s",
             payload["n"], payload["t_start_utc"], config.SERIES_JSON)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    run()
