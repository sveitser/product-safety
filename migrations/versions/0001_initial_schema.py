"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-05-31

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id                  INTEGER PRIMARY KEY,
            reference           TEXT NOT NULL,
            publication_date    TEXT,
            modification_date   TEXT,
            country             TEXT,
            product_category    TEXT,
            product_name        TEXT,
            product_name_specific TEXT,
            brands              TEXT,
            model_types         TEXT,
            risk_types          TEXT,
            risk_description    TEXT,
            legal_provision     TEXT,
            measures            TEXT,
            country_of_origin   TEXT,
            sold_online         TEXT,
            notification_type   TEXT,
            raw_json            TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id          INTEGER PRIMARY KEY,
            alert_id    INTEGER NOT NULL REFERENCES alerts(id),
            filename    TEXT NOT NULL,
            main_picture INTEGER NOT NULL DEFAULT 0,
            local_path  TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_category ON alerts(product_category)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_pubdate ON alerts(publication_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_photos_alert ON photos(alert_id)")
    op.execute("""
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
        )
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS alerts_ai AFTER INSERT ON alerts BEGIN
            INSERT INTO alerts_fts(rowid, reference, product_name,
                product_name_specific, brands, model_types, risk_description,
                country, country_of_origin)
            VALUES (new.id, new.reference, new.product_name,
                new.product_name_specific, new.brands, new.model_types,
                new.risk_description, new.country, new.country_of_origin);
        END
    """)
    op.execute("""
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
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS alerts_au")
    op.execute("DROP TRIGGER IF EXISTS alerts_ai")
    op.execute("DROP TABLE IF EXISTS alerts_fts")
    op.execute("DROP INDEX IF EXISTS idx_photos_alert")
    op.execute("DROP INDEX IF EXISTS idx_alerts_pubdate")
    op.execute("DROP INDEX IF EXISTS idx_alerts_category")
    op.execute("DROP TABLE IF EXISTS photos")
    op.execute("DROP TABLE IF EXISTS alerts")
