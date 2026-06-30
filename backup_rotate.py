"""Weekly backup of the canonical observatory files, with simple retention."""
from __future__ import annotations

import gzip
import logging
import shutil
from datetime import datetime, timezone

import config

log = logging.getLogger("backup")


def _rotate(stem: str) -> None:
    backups = sorted(config.BACKUP_DIR.glob(f"{stem}_*"))
    for old in backups[:max(0, len(backups) - config.BACKUP_KEEP)]:
        old.unlink()
        log.info("pruned old backup %s", old.name)


def _backup_one(src) -> None:
    if not src.exists():
        log.warning("skip backup, missing: %s", src)
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = config.BACKUP_DIR / f"{src.stem}_{stamp}{src.suffix}"
    if config.BACKUP_GZIP:
        dest = dest.with_suffix(dest.suffix + ".gz")
        with open(src, "rb") as fi, gzip.open(dest, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    else:
        shutil.copy2(src, dest)
    log.info("backup -> %s", dest)
    _rotate(src.stem)


def run() -> None:
    for src in (config.HOURLY_CSV, config.HIGHRES_CSV):
        _backup_one(src)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    run()
