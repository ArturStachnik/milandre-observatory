"""Push the observatory CSVs to Baserow: one row per file, same datalogger.

The hourly file and the 5-minute file each go to their own pre-created row in
table 952279, both linked by hand to the same datalogger (VM_MILAMONT). For each
row the script uploads its file, replaces the file field with that single file,
and fills Date debut / Date fin from the first and last timestamp in the CSV.
No rows are created or deleted, so a token without delete permission is enough.

.baserow_env (gitignored):
    BASEROW_API_URL=https://api.baserow.io
    BASEROW_TOKEN=...
    BASEROW_TABLE_ID=952279
    BASEROW_ROW_ID_HOURLY=364
    BASEROW_ROW_ID_5MIN=...
    BASEROW_FILE_FIELD=Fichier de données
    BASEROW_START_FIELD=Date debut
    BASEROW_END_FIELD=Date fin
"""
from __future__ import annotations

import logging
import os

import pandas as pd
import requests

import config

log = logging.getLogger("baserow_push")


def _load_env(path) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing Baserow env file: {path}")
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _date_span(csv_path):
    """First and last calendar date present in the file (ISO yyyy-mm-dd)."""
    s = pd.read_csv(csv_path, usecols=["datetime_utc"])["datetime_utc"]
    s = pd.to_datetime(s, errors="coerce").dropna()
    if s.empty:
        return None, None
    return s.min().date().isoformat(), s.max().date().isoformat()


def _upload(api, token, path) -> dict:
    with open(path, "rb") as fh:
        r = requests.post(f"{api}/api/user-files/upload-file/",
                          headers={"Authorization": f"Token {token}"},
                          files={"file": (os.path.basename(path), fh, "text/csv")},
                          timeout=180)
    r.raise_for_status()
    obj = r.json()
    log.info("uploaded %s -> %s", os.path.basename(path), obj.get("name"))
    return {"name": obj["name"], "visible_name": os.path.basename(path)}


def _push_one(api, token, table, row_id, field, start_field, end_field, csv_path):
    if not row_id:
        log.warning("no row id for %s, skipping", os.path.basename(str(csv_path)))
        return
    if not os.path.exists(csv_path):
        log.warning("skip missing file %s", csv_path)
        return

    file_obj = _upload(api, token, str(csv_path))
    d0, d1 = _date_span(csv_path)
    payload = {field: [file_obj]}
    if d0:
        payload[start_field] = d0
    if d1:
        payload[end_field] = d1

    url = f"{api}/api/database/rows/table/{table}/{row_id}/?user_field_names=true"
    r = requests.patch(url,
                       headers={"Authorization": f"Token {token}",
                                "Content-Type": "application/json"},
                       json=payload, timeout=60)
    r.raise_for_status()
    log.info("patched row %s with %s (%s -> %s)",
             row_id, os.path.basename(str(csv_path)), d0, d1)


def run() -> None:
    env = _load_env(config.BASEROW_ENV)
    api = env.get("BASEROW_API_URL", "https://api.baserow.io").rstrip("/")
    token = env["BASEROW_TOKEN"]
    table = env["BASEROW_TABLE_ID"]
    field = env.get("BASEROW_FILE_FIELD", "Fichier de données")
    start_field = env.get("BASEROW_START_FIELD", "Date debut")
    end_field = env.get("BASEROW_END_FIELD", "Date fin")

    row_hourly = env.get("BASEROW_ROW_ID_HOURLY") or env.get("BASEROW_ROW_ID")
    row_5min = env.get("BASEROW_ROW_ID_5MIN")

    _push_one(api, token, table, row_hourly, field, start_field, end_field, config.HOURLY_CSV)
    _push_one(api, token, table, row_5min, field, start_field, end_field, config.HIGHRES_CSV)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    run()
