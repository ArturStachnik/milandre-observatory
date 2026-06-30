"""Upload the /series overview JSON to the website over SFTP, atomically.

Credentials and the remote directory are read from an env file (default
.sftp_env next to this script) so nothing secret lives in the repo:

    SFTP_HOST=ops.ftp.infomaniak.com
    SFTP_PORT=22
    SFTP_USER=ops_artur
    SFTP_PASS=...                       # or SFTP_KEY=/home/ubuntu/.ssh/id_xxx
    SFTP_REMOTE_DIR=/home/clients/<id>/milab/images/series
"""
from __future__ import annotations

import logging
import os

import paramiko

import config

log = logging.getLogger("publish_series")


def _load_env(path) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing SFTP env file: {path}")
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def run() -> None:
    env = _load_env(config.SFTP_ENV)
    host, port = env["SFTP_HOST"], int(env.get("SFTP_PORT", "22"))
    user, remote_dir = env["SFTP_USER"], env["SFTP_REMOTE_DIR"]

    local = str(config.SERIES_JSON)
    remote = f"{remote_dir.rstrip('/')}/{config.SERIES_REMOTE_FILENAME}"
    remote_tmp = remote + ".tmp"

    transport = paramiko.Transport((host, port))
    if env.get("SFTP_KEY"):
        transport.connect(username=user,
                          pkey=paramiko.RSAKey.from_private_key_file(env["SFTP_KEY"]))
    else:
        transport.connect(username=user, password=env["SFTP_PASS"])
    try:
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(local, remote_tmp)               # upload beside the live file
        try:
            sftp.remove(remote)                   # rename cannot overwrite on some servers
        except IOError:
            pass
        sftp.rename(remote_tmp, remote)           # atomic swap into place
        log.info("published -> %s", remote)
    finally:
        transport.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT, datefmt=config.LOG_DATEFMT)
    run()
