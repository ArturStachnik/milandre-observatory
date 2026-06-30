"""Fetch the last 90 days of BAFU station 6748 (Boncourt - Milandre Amont).

The hydrodaten portal exposes no public REST endpoint; its front-end charts are
backed by static Plotly JSON descriptors, each a rolling 90-day window at the
native 5-minute cadence. We query those descriptors and return one wide frame
at 5-minute resolution.
"""
from __future__ import annotations

import logging

import pandas as pd
import requests

import config

log = logging.getLogger("fetch_bafu")


def _fetch_chart(kind: str):
    url = f"{config.BAFU_BASE_URL}/{kind}/{config.BAFU_STATION_ID}_{kind}_{config.BAFU_LANG}.json"
    log.info("GET %s", url)
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT, "Accept": "*/*"},
                     timeout=config.HTTP_TIMEOUT)
    if r.status_code == 404:
        log.warning("  404 - station has no '%s' chart, skipping", kind)
        return None
    r.raise_for_status()
    return r.json()


def _traces_to_long(payload: dict, name_to_col: dict) -> pd.DataFrame:
    rows = []
    for tr in payload.get("plot", {}).get("data", []):
        name = tr.get("name")
        if name not in name_to_col:
            continue
        x, y = tr.get("x") or [], tr.get("y") or []
        if not x or not y:
            continue
        ts = pd.to_datetime(x, utc=True, errors="coerce")
        vals = pd.to_numeric(y, errors="coerce")
        df = pd.DataFrame({"datetime_utc": ts, "column": name_to_col[name], "value": vals})
        rows.append(df.dropna(subset=["datetime_utc"]))
    if not rows:
        return pd.DataFrame(columns=["datetime_utc", "column", "value"])
    return pd.concat(rows, ignore_index=True)


def fetch_bafu_5min() -> pd.DataFrame:
    """Return a wide 5-minute frame: datetime_utc (UTC-naive) plus observed columns."""
    parts = []
    for kind, name_to_col in config.BAFU_CHART_KINDS.items():
        payload = _fetch_chart(kind)
        if payload is None:
            continue
        part = _traces_to_long(payload, name_to_col)
        if not part.empty:
            parts.append(part)

    if not parts:
        log.warning("no BAFU data retrieved")
        return pd.DataFrame(columns=["datetime_utc"])

    long_df = pd.concat(parts, ignore_index=True)
    wide = (long_df.pivot_table(index="datetime_utc", columns="column",
                                values="value", aggfunc="last").sort_index())
    wide.columns.name = None
    wide = wide.reset_index()

    if config.BAFU_DISCHARGE_COL in wide.columns:               # m3/s -> L/s
        wide[config.BAFU_DISCHARGE_COL] = wide[config.BAFU_DISCHARGE_COL] * 1000.0

    wide["datetime_utc"] = pd.to_datetime(wide["datetime_utc"], utc=True).dt.tz_convert(None)
    log.info("BAFU: %d rows, %s -> %s", len(wide),
             wide["datetime_utc"].min(), wide["datetime_utc"].max())
    return wide


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    print(fetch_bafu_5min().tail().to_string())
