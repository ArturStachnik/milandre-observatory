"""Configuration for the Milamont observatory daily job.

Single place to change stations, URLs, paths, cadences and retention.
Persistence is isolated in store.py, so this product can later be pointed at a
database without touching the fetch or merge logic.
"""
from pathlib import Path
import os

# ----------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MILAMONT_OBS_DATA", ROOT / "data"))
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
for _d in (DATA_DIR, BACKUP_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Canonical outputs: single growing files, never one-per-day.
HOURLY_CSV = DATA_DIR / "milamont_observatory_hourly.csv"
HIGHRES_CSV = DATA_DIR / "milamont_observatory_5min.csv"

# Single combined seed: the operator places this one file in data/ at first
# deploy (built once with make_seed.py). The daily job only grows it.
# (No raw reconstruction/master files are needed by the operational job.)

# ----------------------------------------------------------------- stations
BAFU_STATION_ID = "6748"                                   # Boncourt - Milandre Amont
BAFU_BASE_URL = "https://www.hydrodaten.admin.ch/plots"
BAFU_LANG = "en"

METEOSWISS_OGD_BASE = "https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items"
FAHY_STATION_ID = "fah"
FAHY_ASSET_PREFIX = "ogd-smn_fah_h_"                        # h = hourly granularity

# BAFU Plotly chart kinds -> internal column names.
BAFU_CHART_KINDS = {
    "p_q_90days":          {"Discharge": "q_obs_l_s", "Water level": "level_m"},
    "temperature_90days":  {"Temperature": "water_temp_c"},
    "conductivity_90days": {"Conductivity": "conductivity_us_cm"},
    "turbidity_90days":    {"Turbidity": "turbidity_ntu"},
}
BAFU_DISCHARGE_COL = "q_obs_l_s"                            # arrives in m3/s, converted to L/s

# Fahy SMN raw codes -> internal names (water temp comes from BAFU, so Fahy t is air).
FAHY_RENAME = {"rre150h0": "p_mm_h", "tre200h0": "t_air_c"}
FAHY_VARS = ["p_mm_h", "t_air_c"]
FAHY_MODE = "recent"   # current year so far + last 24-48h; self-heals gaps each day

# ----------------------------------------------------------------- runtime
HTTP_TIMEOUT = 60
USER_AGENT = "Milamont-observatory (research; SISKA)"

BACKUP_KEEP = 8        # weekly job keeps this many copies
BACKUP_GZIP = True

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# ----------------------------------------------------------------- /series web publication
SERIES_JSON = DATA_DIR / "series_milamont_overview.txt"   # local build target
SERIES_STEP_H = 6                                          # decimation window (hours)
SERIES_LABEL = "Milamont discharge"
SERIES_REMOTE_FILENAME = "series_milamont_overview.txt"    # name the /series viewer fetches
SFTP_ENV = ROOT / ".sftp_env"                             # SFTP credentials (gitignored)

# ----------------------------------------------------------------- Baserow push
BASEROW_ENV = ROOT / ".baserow_env"   # token + target row (gitignored)
