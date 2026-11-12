"""Konfiguration: liegt in einkauf-data/config.json neben dem Programm."""
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EINKAUF_DATA", BASE_DIR / "einkauf-data"))
CONFIG_FILE = DATA_DIR / "config.json"


def load():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {"host": "0.0.0.0", "port": 8080, "db": None, "setup_done": False, "firma": ""}
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        save(cfg)
    if os.environ.get("EINKAUF_PORT"):
        cfg["port"] = int(os.environ["EINKAUF_PORT"])
    return cfg


def save(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_FILE)


def db_url(db):
    if db["type"] == "sqlite":
        return URL.create("sqlite", database=str(DATA_DIR / "einkauf.db"))
    return URL.create(
        "mysql+pymysql",
        username=db["user"],
        password=db["password"],
        host=db["host"],
        port=int(db["port"]),
        database=db["name"],
        query={"charset": "utf8mb4"},
    )


def fernet_key(secret):
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
