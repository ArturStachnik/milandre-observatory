"""Fetch observed Fahy precipitation and air temperature (hourly) from the
MeteoSwiss OGD STAC.

Parsing mirrors the forecaster's pipeline (same assets, same column renames),
so the values line up exactly with master.csv.
"""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests

import config

log = logging.getLogger("fetch_fahy")
_ITEM = f"{config.METEOSWISS_OGD_BASE}/{config.FAHY_STATION_ID}"


def _list_assets() -> dict:
    r = requests.get(_ITEM, timeout=30)
    r.raise_for_status()
    out = {}
    for name, meta in r.json().get("assets", {}).items():
        if name.startswith(config.FAHY_ASSET_PREFIX) and name.endswith(".csv"):
            out[name] = meta["href"]
    if not out:
        raise RuntimeError("no hourly Fahy assets in STAC listing")
    return out


def _select(assets: dict, mode: str) -> list:
    if mode == "full":
        return list(assets.values())
    tags = {"now": ["now"], "recent": ["recent", "now"]}.get(mode)
    if tags is None:
        raise ValueError(f"unknown mode {mode}")
    return [assets[f"{config.FAHY_ASSET_PREFIX}{t}.csv"]
            for t in tags if f"{config.FAHY_ASSET_PREFIX}{t}.csv" in assets]


def _read(href: str) -> pd.DataFrame:
    r = requests.get(href, timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), sep=";", low_memory=False)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    ts_col = next((c for c in ("reference_timestamp", "REFERENCE_TS", "reference_TS")
                   if c in df.columns), None)
    if ts_col is None:
        raise RuntimeError(f"no timestamp column; got {list(df.columns)}")
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df[ts_col], format="%d.%m.%Y %H:%M", errors="coerce")
    df = df.dropna(subset=["datetime_utc"])
    df = df.rename(columns={k: v for k, v in config.FAHY_RENAME.items() if k in df.columns})
    for c in config.FAHY_VARS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    keep = ["datetime_utc"] + [c for c in config.FAHY_VARS if c in df.columns]
    return df[keep]


def fetch_fahy_hourly(mode: str = None) -> pd.DataFrame:
    """Return datetime_utc (UTC-naive), p_mm_h, t_air_c at hourly resolution."""
    mode = mode or config.FAHY_MODE
    frames = [_normalise(_read(h)) for h in _select(_list_assets(), mode)]
    if not frames:
        return pd.DataFrame(columns=["datetime_utc"] + config.FAHY_VARS)
    full = (pd.concat(frames, ignore_index=True)
            .sort_values("datetime_utc")
            .drop_duplicates("datetime_utc", keep="last"))
    if full["datetime_utc"].dt.tz is not None:
        full["datetime_utc"] = full["datetime_utc"].dt.tz_convert(None)
    log.info("Fahy: %d rows, %s -> %s", len(full),
             full["datetime_utc"].min(), full["datetime_utc"].max())
    return full.reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    print(fetch_fahy_hourly().tail().to_string())
