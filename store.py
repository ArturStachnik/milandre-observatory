"""Persistence layer for the observatory.

Everything that touches storage lives here. To move from CSV to a database
later, reimplement read_table / write_table / upsert with the same signatures;
the fetch and merge code does not change.
"""
from __future__ import annotations

import logging
import os

import pandas as pd

log = logging.getLogger("store")
KEY = "datetime_utc"


def read_table(path) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if KEY in df.columns:
        df[KEY] = pd.to_datetime(df[KEY], errors="coerce")
    return df


def write_table(df: pd.DataFrame, path) -> None:
    """Atomic write: temp file then replace, so a crash never leaves a half file."""
    if KEY in df.columns:
        df = df.sort_values(KEY)
    tmp = f"{path}.tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)
    log.info("wrote %d rows -> %s", len(df), path)


def upsert(path, new: pd.DataFrame) -> pd.DataFrame:
    """Merge new rows into the canonical table.

    New non-null values win on a shared timestamp; existing values fill any gaps
    the new frame leaves null (so a transient null from a source never erases a
    good value). Genuinely new timestamps are appended. Returns the merged frame.
    """
    if new is None or new.empty:
        log.info("upsert: nothing new")
        return read_table(path)

    new = new.copy()
    new[KEY] = pd.to_datetime(new[KEY], errors="coerce")
    new = new.dropna(subset=[KEY])

    existing = read_table(path)
    if existing.empty:
        merged = new
    else:
        merged = (new.set_index(KEY)
                  .combine_first(existing.set_index(KEY))
                  .reset_index())
    write_table(merged, path)
    return merged
