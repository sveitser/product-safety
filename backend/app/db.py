import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

DB_PATH = Path(os.environ.get("DB_PATH", "data/safety.db"))

_ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
    command.upgrade(cfg, "head")
