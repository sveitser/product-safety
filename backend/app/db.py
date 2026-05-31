import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "data/safety.db"))


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id                  INTEGER PRIMARY KEY,
                reference           TEXT NOT NULL,
                publication_date    TEXT,
                modification_date   TEXT,
                country             TEXT,
                product_category    TEXT,
                product_name        TEXT,
                product_name_specific TEXT,
                brands              TEXT,  -- JSON array of strings
                model_types         TEXT,  -- JSON array of strings
                risk_types          TEXT,  -- JSON array of strings
                risk_description    TEXT,
                legal_provision     TEXT,
                measures            TEXT,  -- JSON array of strings
                country_of_origin   TEXT,
                sold_online         TEXT,
                notification_type   TEXT,
                raw_json            TEXT   -- full JSON from API
            );

            CREATE TABLE IF NOT EXISTS photos (
                id          INTEGER PRIMARY KEY,
                alert_id    INTEGER NOT NULL REFERENCES alerts(id),
                filename    TEXT NOT NULL,
                main_picture INTEGER NOT NULL DEFAULT 0,
                local_path  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_category
                ON alerts(product_category);
            CREATE INDEX IF NOT EXISTS idx_alerts_pubdate
                ON alerts(publication_date DESC);
            CREATE INDEX IF NOT EXISTS idx_photos_alert
                ON photos(alert_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS alerts_fts USING fts5(
                reference,
                product_name,
                product_name_specific,
                brands,
                model_types,
                risk_description,
                country,
                country_of_origin,
                content=alerts,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS alerts_ai AFTER INSERT ON alerts BEGIN
                INSERT INTO alerts_fts(rowid, reference, product_name,
                    product_name_specific, brands, model_types, risk_description,
                    country, country_of_origin)
                VALUES (new.id, new.reference, new.product_name,
                    new.product_name_specific, new.brands, new.model_types,
                    new.risk_description, new.country, new.country_of_origin);
            END;

            CREATE TRIGGER IF NOT EXISTS alerts_au AFTER UPDATE ON alerts BEGIN
                INSERT INTO alerts_fts(alerts_fts, rowid, reference, product_name,
                    product_name_specific, brands, model_types, risk_description,
                    country, country_of_origin)
                VALUES ('delete', old.id, old.reference, old.product_name,
                    old.product_name_specific, old.brands, old.model_types,
                    old.risk_description, old.country, old.country_of_origin);
                INSERT INTO alerts_fts(rowid, reference, product_name,
                    product_name_specific, brands, model_types, risk_description,
                    country, country_of_origin)
                VALUES (new.id, new.reference, new.product_name,
                    new.product_name_specific, new.brands, new.model_types,
                    new.risk_description, new.country, new.country_of_origin);
            END;
        """)
    conn.close()
