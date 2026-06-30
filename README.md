# Milandre / Milamont observatory

An automated daily pipeline that retrieves observed hydrological and
meteorological data for the Milamont internal tributary of the Milandre karst
system (Swiss Jura), merges it with the long term Milamont reconstruction into
two continuously updated CSV products, and distributes them through three
independent channels: a single growing file on disk, an overview series
published to the laboratory website, and structured attachments pushed to the
ISSKA Baserow database.

The project is operational. It runs unattended on a virtual machine under
`systemd`, once a day, and needs no manual intervention.

---

## Engineering highlights

- **Three heterogeneous API integrations in one pipeline:** an undocumented JSON
  source reverse-engineered from a Plotly front end (BAFU), a STAC catalog
  consumed through asset discovery (MeteoSwiss), and a token-authenticated REST
  API (Baserow).
- **Idempotent writes:** each run upserts the rolling window into a single
  canonical file, so re-runs and late provider corrections never duplicate or
  lose data; the Baserow push overwrites fixed rows, so no watermark is needed.
- **Atomic delivery:** local files and the SFTP upload both use a
  temp-then-rename, so a reader never sees a half written file.
- **Least-privilege automation:** the database token has create, read and update
  but not delete, so the job is structurally unable to remove data.
- **Self-healing tail:** the 90 day window is re-fetched and merged daily,
  absorbing provider revisions automatically.
- **Graceful degradation:** a missing source variable (HTTP 404) is logged and
  skipped, never fatal.
- **Swappable persistence:** all storage sits behind a three-function seam
  (`store.py`), so moving to a time series database touches one module.
- **Unattended operation:** a four-step daily job under `systemd`, with weekly
  rotated backups.

---

## Table of contents

1. [What it does](#what-it-does)
2. [API integrations](#api-integrations)
   - [1. BAFU hydrological data](#1-bafu-hydrological-data-hydrodaten)
   - [2. MeteoSwiss open data (OGD STAC)](#2-meteoswiss-open-data-ogd-stac)
   - [3. Website publication over SFTP](#3-website-publication-over-sftp-series)
   - [4. Baserow database (REST API)](#4-baserow-database-rest-api)
3. [Data products and schemas](#data-products-and-schemas)
4. [Design principles](#design-principles)
5. [Repository layout](#repository-layout)
6. [Installation and deployment](#installation-and-deployment)
7. [Credentials](#credentials)
8. [Operations and troubleshooting](#operations-and-troubleshooting)
9. [Reproducing the historical seed](#reproducing-the-historical-seed)
10. [Migrating to a database backend](#migrating-to-a-database-backend)
11. [Citation](#citation)

---

## What it does

Every day the pipeline performs four steps, chained in a single `systemd`
service:

1. **Build.** Download the last 90 days of observations from the BAFU station
   (discharge, water level, water temperature, conductivity, turbidity) and the
   matching window of precipitation and air temperature from the MeteoSwiss
   Fahy station, then merge both into two canonical CSV files using an
   idempotent upsert with atomic writes.
2. **Export.** Build a decimated overview of discharge and precipitation in the
   exact JSON schema the website time series viewer consumes.
3. **Publish.** Upload that JSON over SFTP to the website, replacing the file
   the `/series` page reads, so the public chart refreshes automatically.
4. **Push.** Upload both CSV files to the ISSKA Baserow database as attachments,
   one row per file, and fill the start and end dates from the data.

A second weekly service keeps a small rotation of compressed backups.

```
                         +--------------------------+
   BAFU hydrodaten  ---> |                          | --->  hourly CSV  --+
   (Plotly JSON)         |   build_observatory.py   |                     |
                         |   fetch + merge + upsert | --->  5-min CSV  ---+
   MeteoSwiss OGD   ---> |                          |                     |
   (STAC + CSV)          +--------------------------+                     |
                                                                          |
        +------------------------------------------------------------------+
        |
        +-->  export_series.py  -->  /series overview JSON  --SFTP-->  website /series
        |
        +-->  baserow_push.py   --REST-->  Baserow rows (file attachments + dates)
```

---

## API integrations

Four distinct external systems are integrated, each with its own protocol, authentication model and failure modes. The code
keeps every integration in its own module so each can be tested and replaced in
isolation.

### 1. BAFU hydrological data (hydrodaten)

**Module:** `fetch_bafu.py`
**Source:** Federal Office for the Environment (BAFU/FOEN), station 6748,
Boncourt - Milandre Amont, NAQUA network.

The public hydrodaten portal exposes **no documented REST API**. Its front end
renders charts from static Plotly JSON descriptors, one per variable, each
holding a rolling 90 day window at the native 5 minute cadence. The fetcher
queries those descriptors directly:

```
GET https://www.hydrodaten.admin.ch/plots/{kind}/6748_{kind}_en.json
```

with `kind` in `p_q_90days` (discharge + water level), `temperature_90days`,
`conductivity_90days`, `turbidity_90days`. No authentication is required.

Each response is a Plotly figure. The relevant series live under
`plot.data[*]`, where every trace carries parallel `x` (ISO timestamps) and `y`
(values) arrays. The module:

- maps each named trace to an internal column (for example the trace
  `Discharge` to `q_obs_l_s`),
- reshapes the traces into one wide frame on a unified 5 minute timestamp index,
- converts discharge from m3/s to L/s,
- normalises timestamps to UTC naive to match the rest of the pipeline.

**Robustness.** A missing variable returns HTTP 404 (station 6748 publishes no
turbidity chart, for example); the fetcher logs it and continues with the
remaining variables rather than failing. Because the source is a 90 day rolling
window, the recent tail is re-fetched every day and any late corrections by BAFU
are absorbed by the upsert (see [Design principles](#design-principles)).

### 2. MeteoSwiss open data (OGD STAC)

**Module:** `fetch_fahy.py`
**Source:** MeteoSwiss SwissMetNet station Fahy, via the federal open data
SpatioTemporal Asset Catalog (STAC).

MeteoSwiss publishes its open data through a STAC API. The fetcher first
resolves the station item to discover its data assets:

```
GET https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/fah
```

The JSON response contains an `assets` map. The module selects the hourly assets
named `ogd-smn_fah_h_now.csv` (last 24 to 48 hours) and `ogd-smn_fah_h_recent.csv`
(current year), follows their `href`, downloads the semicolon delimited CSVs,
parses the `reference_timestamp` field (`dd.mm.YYYY HH:MM`), and renames the raw
MeteoSwiss codes to internal names: `rre150h0` to `p_mm_h` (hourly precipitation
sum) and `tre200h0` to `t_air_c` (hourly mean air temperature). No
authentication is required; the open data licence requires citing the source.

This asset discovery step matters: rather than hard coding download URLs that
change over time, the pipeline asks the catalog what is available and follows
the links it returns, which is the intended STAC access pattern.

### 3. Website publication over SFTP (`/series`)

**Modules:** `export_series.py` (build) and `publish_series.py` (transfer).

The laboratory website hosts a public time series viewer at `/series`. It reads
a single JSON document and renders discharge against precipitation. The pipeline
regenerates that document from the hourly product and ships it.

**The JSON contract.** `export_series.py` decimates the hourly record to 6 hour
windows and produces exactly the schema the viewer expects:

```json
{
  "label": "Milamont discharge",
  "t_start_utc": "1990-01-30 18:00:00",
  "step_h": 6,
  "n": 53199,
  "var_name": "Discharge",
  "var_units": "L/s",
  "values": [ ... ],
  "recon":  [ ... ],
  "secondary": {
    "name": "Precipitation",
    "units": "mm/h",
    "reversed": true,
    "values": [ ... ]
  },
  "note": "Overview decimated to 6-hourly windows."
}
```

`values` holds observed discharge and is null where only the reconstruction
exists; `recon` holds reconstructed discharge and is null where observed. They
are complementary: each 6 hour window carries the mean of the observed discharge
in `values` or, where only the reconstruction exists, the mean of the
reconstructed discharge in `recon`. The `secondary` block carries precipitation
(mm/h) drawn on an inverted top axis. The series is a regular grid; the viewer
reconstructs timestamps from `t_start_utc` plus `step_h * index`.

**The transfer.** `publish_series.py` uploads the file over SFTP using `paramiko`,
**atomically**: it writes to a temporary remote name and then renames it over the
live file, so a reader never sees a half written document.

- Local source: `data/series_milamont_overview.txt`
- Remote target: `${SFTP_REMOTE_DIR}/series_milamont_overview.txt`, where
  `SFTP_REMOTE_DIR` is the website `images/series` folder
  (for example `/home/clients/<id>/milab/images/series`)
- Public URL the viewer fetches: `/images/series/series_milamont_overview.txt`

The remote file name is `SERIES_REMOTE_FILENAME` in `config.py` and must match
the name the `/series` block requests. Credentials live in `.sftp_env` (see
[Credentials](#credentials)).

### 4. Baserow database (REST API)

**Module:** `baserow_push.py`
**Target:** ISSKA Baserow database 279587.

Baserow exposes a clean REST API authenticated with a database token
(`Authorization: Token <token>`). In this database, measurement data are stored
as **file attachments on rows**, not as one row per measurement. The relevant
tables are:

| Table  | Role                          | Key field        |
|--------|-------------------------------|------------------|
| 653094 | Datalogger catalogue (Sondes) | `Numéro de série`|
| 653111 | Stations                      | `Nom`            |
| 952279 | Data rows (file attachments)  | links + files    |
| 745188 | Deployments                   | dates + links    |

The observatory is modelled as one virtual datalogger, `VM_MILAMONT`, registered
once by hand in the catalogue (653094). In table 952279 it owns **two rows**,
both linked to that datalogger and to the station: one for the hourly file and
one for the 5 minute file.

**Upload is a two call sequence per file.** First the CSV is uploaded as a user
file:

```
POST {api}/api/user-files/upload-file/      (multipart, field "file")
  -> { "name": "<internal-hashed-name>.csv", "url": ..., "original_name": ... }
```

Then the target row's file field is rewritten with that descriptor, together
with the start and end dates read from the file itself:

```
PATCH {api}/api/database/rows/table/952279/{row_id}/?user_field_names=true
{
  "Fichier de données": [ { "name": "<from upload>", "visible_name": "milamont_observatory_hourly.csv" } ],
  "Date debut": "1990-01-01",
  "Date fin":   "2026-06-30"
}
```

`user_field_names=true` lets the payload use human field names instead of
numeric field ids. `Date debut` and `Date fin` are computed from the first and
last `datetime_utc` in the CSV, so the catalogue always shows the period each
file covers without any manual editing.

**Idempotency by design.** The script never creates or deletes rows; it
overwrites the file field and dates on two fixed, pre-created rows. Because each
push replaces the whole cell with the current file, there is no risk of
duplicates and no need for a watermark or row mapping. The token therefore needs
only create, read and update permissions, **not delete**, which bounds the blast
radius of the automation: it is structurally incapable of removing data.

This mirrors the pattern ISSKA already uses for its Notehub loggers, so the
virtual observatory logger behaves like any other entry in the database.

---

## Data products and schemas

Two canonical files live in `data/`, each updated in place (never one file per
day).

**Hourly** `milamont_observatory_hourly.csv` is the long record. It is seeded
once from the Milamont reconstruction and the historical Fahy series, then grows
with the live feed.

| column                | meaning                                              |
|-----------------------|------------------------------------------------------|
| `datetime_utc`        | hourly timestamp, UTC naive                          |
| `q_l_s`               | combined discharge in L/s                            |
| `q_source`            | `obs` (measured) or `recon` (reconstructed)          |
| `level_m`             | water level, BAFU                                    |
| `water_temp_c`        | spring water temperature, BAFU                       |
| `conductivity_us_cm`  | conductivity, BAFU                                   |
| `turbidity_ntu`       | turbidity, BAFU (empty for station 6748)             |
| `p_mm_h`              | precipitation, Fahy                                  |
| `t_air_c`             | air temperature, Fahy                                |

**5 minute** `milamont_observatory_5min.csv` is the live observed feed at native
resolution. It has no historical seed (BAFU only publishes the last 90 days at 5
minutes), so it starts at the beginning of that window and accumulates.

| column                | meaning                                              |
|-----------------------|------------------------------------------------------|
| `datetime_utc`        | 5 minute timestamp, UTC naive                        |
| `q_obs_l_s`           | observed discharge in L/s                            |
| `level_m`, `water_temp_c`, `conductivity_us_cm`, `turbidity_ntu` | BAFU |
| `p_mm_h`, `t_air_c`   | Fahy values placed at the exact hour, null between   |

The two products differ on purpose. The hourly file mixes reconstruction and
observation, so discharge is a single combined column with a `q_source` flag.
The 5 minute file is pure observation, so discharge is `q_obs_l_s` with no flag.
Fahy is hourly; in the 5 minute file its values appear only at minute zero of
each hour and are null in between, never interpolated.

---

## Design principles

- **One growing file, not thousands.** Each run reads the canonical file,
  fetches the recent window, and upserts: overlapping timestamps are refreshed,
  new ones appended. The hourly file grows by about 24 rows per day, the 5
  minute file by about 288.
- **Atomic writes.** Every file is written to a temporary path and then renamed
  over the target, so a crash never leaves a half written file.
- **Self healing tail.** The recent 90 days are re-fetched daily; if BAFU
  revises late values, the upsert overwrites them. The upsert prefers new non
  null values but keeps existing values where the new frame is null, so a
  transient gap from a source never erases good data.
- **No fabricated data.** Hourly Fahy values are not interpolated onto the 5
  minute grid; they sit only at their real timestamp.
- **Provenance preserved.** Observed and reconstructed discharge are never
  silently mixed; the `q_source` flag records which is which.

---

## Repository layout

```
observatory/
├── config.py              # paths, station ids, endpoints, cadences, retention
├── fetch_bafu.py          # BAFU hydrodaten (Plotly JSON) -> 5-min frame
├── fetch_fahy.py          # MeteoSwiss OGD STAC -> hourly precipitation + air temp
├── build_observatory.py   # daily build: fetch, merge, upsert both files
├── export_series.py       # build the /series overview JSON
├── publish_series.py      # SFTP upload of the overview JSON (atomic)
├── baserow_push.py        # upload both CSVs to Baserow (one row per file + dates)
├── backup_rotate.py       # weekly compressed backups with retention
├── store.py               # persistence layer (atomic read/write/upsert seam)
├── make_seed.py           # one-off: build the hourly seed from reconstruction + master
├── requirements.txt
├── systemd/
│   ├── milamont-observatory.service        # daily: build -> export -> publish -> push
│   ├── milamont-observatory.timer          # 06:15 UTC
│   ├── milamont-observatory-backup.service
│   └── milamont-observatory-backup.timer   # Mondays 06:45 UTC
├── .sftp_env.example
├── .baserow_env.example
└── data/                  # not in git; canonical files, backups, logs live here
```

---

## Installation and deployment

Tested on Ubuntu with a `micromamba` environment named `switzerland`.

```bash
# 1. unpack into the project directory
cd ~ && unzip milandre-observatory-vm.zip          # creates ~/observatory

# 2. dependencies
micromamba run -n switzerland pip install -r ~/observatory/requirements.txt

# 3. confirm the interpreter path used by the systemd units
micromamba run -n switzerland which python
# expected: /home/ubuntu/micromamba/envs/switzerland/bin/python
# if different, edit ExecStart in the two *.service files

# 4. credentials (see next section)
cd ~/observatory
cp .sftp_env.example .sftp_env       && nano .sftp_env       && chmod 600 .sftp_env
cp .baserow_env.example .baserow_env && nano .baserow_env    && chmod 600 .baserow_env

# 5. manual end-to-end test
micromamba run -n switzerland python build_observatory.py
micromamba run -n switzerland python export_series.py
micromamba run -n switzerland python publish_series.py
micromamba run -n switzerland python baserow_push.py

# 6. install and enable the timers
sudo cp systemd/milamont-observatory*.service /etc/systemd/system/
sudo cp systemd/milamont-observatory*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now milamont-observatory.timer
sudo systemctl enable --now milamont-observatory-backup.timer

# 7. verify
systemctl list-timers | grep milamont-observatory
sudo systemctl start milamont-observatory.service
journalctl -u milamont-observatory.service -n 80 --no-pager
```

The daily service runs the four steps in order; if one fails, `systemd` stops
and marks the unit failed, so problems are visible. The build seeds the hourly
file automatically on first run if it is present in `data/`.

### First run: the hourly seed

The hourly product is shipped pre-seeded as
`data/milamont_observatory_hourly.csv` (history back to 1990). The 5 minute file
is created on the first build from the live BAFU window. No raw reconstruction or
master files are needed on the VM.

### Baserow one-time setup

1. In the catalogue (table 653094) create a datalogger `VM_MILAMONT`.
2. In table 952279 create two rows, both linked to `VM_MILAMONT` and to the
   station, file fields empty: one for hourly, one for 5 minute.
3. Read each row id from its URL and set `BASEROW_ROW_ID_HOURLY` and
   `BASEROW_ROW_ID_5MIN` in `.baserow_env`.

---

## Credentials

Two environment files hold secrets. **Both are gitignored** and never leave the
VM. Copy each `.example`, fill it in, and `chmod 600` it.

`.sftp_env` (for `/series` publication):

```
SFTP_HOST=ops.ftp.infomaniak.com
SFTP_PORT=22
SFTP_USER=...
SFTP_PASS=...                       # or SFTP_KEY=/path/to/private/key
SFTP_REMOTE_DIR=/home/clients/<id>/milab/images/series
```

Note: write keys as `NAME=value` with no `export` prefix and no quotes; the
loader parses each line literally.

`.baserow_env` (for the database push):

```
BASEROW_API_URL=https://api.baserow.io
BASEROW_TOKEN=...                    # needs create + read + update (no delete)
BASEROW_TABLE_ID=952279
BASEROW_ROW_ID_HOURLY=...
BASEROW_ROW_ID_5MIN=...
BASEROW_FILE_FIELD=Fichier de données
BASEROW_START_FIELD=Date debut
BASEROW_END_FIELD=Date fin
```

---

## Operations and troubleshooting

**Check the schedule and the last automated run:**

```bash
systemctl list-timers | grep milamont-observatory
journalctl -u milamont-observatory.service --since today -n 80 --no-pager
```

A healthy run logs, in order: BAFU and Fahy fetch lines and
`observatory update complete`; `wrote /series overview`; `published ->`;
two `uploaded` lines and two `patched row` lines for Baserow.

**Common issues:**

- *BAFU turbidity 404.* Expected for station 6748; that column stays empty.
- *SFTP `Authentication failed`.* Almost always a malformed `.sftp_env`: an
  `export` prefix, quotes around values, or the wrong auth method (password vs
  key). Keys must be bare `NAME=value`.
- *Baserow `404 ... /<row>/`.* The row id in `.baserow_env` is wrong or still a
  placeholder; set the numeric id from the row URL.
- *Baserow `401/403`.* The token lacks update permission on the base.
- *A package is missing under systemd.* The units call the environment's python
  directly; confirm the `ExecStart` path matches `which python`.

Backups land in `data/backups/` as gzipped copies, with the last 8 kept
(configurable via `BACKUP_KEEP` in `config.py`).

---

## Reproducing the historical seed

The hourly seed is built once by `make_seed.py` from the Milamont reconstruction
and the historical Fahy record. It is kept for reproducibility and is not part
of the daily job:

```bash
python make_seed.py reconstruction.csv master.csv data/milamont_observatory_hourly.csv
```

- `reconstruction.csv`: `datetime_utc, q_obs, q_rec, bf_rec, qf_rec`
- `master.csv`: must contain `datetime_utc, q_l_s, p_mm_h, t_c`

The combined discharge is observed where measured, reconstructed where not, with
`q_source` flagging each.

---

## Migrating to a database backend

All persistence is isolated in `store.py` (`read_table`, `write_table`,
`upsert`). The fetchers and the merge logic depend only on those three
functions. To move from CSV files to a time series database, reimplement them
against the new backend and nothing else changes. This is the intended path for
the 5 minute product, which grows fastest and is the natural first candidate for
a dedicated database.

---

## Citation

If you use this pipeline or its data products, please cite the discharge
reconstruction it builds on, and acknowledge the software.

**Reconstruction (data and method).** Stachnik, A. (2026). Machine learning
reconstruction and forecasting of a karst tributary in Milandre Cave, Swiss
Jura. *Hydrology and Earth System Sciences* (HESS), under review. A DOI will be
added on publication.

**Software (this pipeline).** Stachnik, A. (2026). *Milandre / Milamont
observatory* [software]. ISSKA.

A `CITATION.cff` file is included, so GitHub shows a "Cite this repository"
button with these details on the repository page.

---

## Sources and attribution

- Hydrological data: BAFU/FOEN, station 6748 (Boncourt - Milandre Amont), NAQUA.
- Meteorological data: MeteoSwiss, SwissMetNet station Fahy, federal open data.
- Reconstruction: Milamont karst discharge reconstruction (ISSKA).

Maintained at ISSKA. For questions about the data sources, cite the providers
above; for the pipeline itself, see the module docstrings, which document each
step in detail.
