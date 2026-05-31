import json
from pathlib import Path

import pytest


def test_init_db_creates_tables(tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "alerts" in tables
    assert "photos" in tables
    conn.close()


def test_init_db_idempotent(tmp_db: Path) -> None:
    import backend.app.db as db_mod

    db_mod.init_db()  # second call must not raise
    conn = db_mod.get_conn()
    conn.close()


def test_get_conn_wal_mode(tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()


def _make_alert(alert_id: int = 1) -> dict:
    return {
        "id": alert_id,
        "reference": f"SR/0000{alert_id}/26",
        "publication_date": "2026-01-01T00:00:00Z",
        "modification_date": "2026-01-02T00:00:00Z",
        "country": "Germany",
        "product_category": "TOYS",
        "product_name": "Test Toy",
        "product_name_specific": "Specific name",
        "brands": json.dumps(["BrandA"]),
        "model_types": json.dumps(["Model1"]),
        "risk_types": json.dumps(["CHOKING"]),
        "risk_description": "Small parts risk",
        "legal_provision": "GPSD Article 5",
        "measures": json.dumps(["RECALL"]),
        "country_of_origin": "China",
        "sold_online": "YES",
        "notification_type": "ARTICLE_12",
        "raw_json": "{}",
    }


def test_upsert_insert(tmp_db: Path) -> None:
    import backend.app.db as db_mod
    from scraper.ingest import upsert_alert

    conn = db_mod.get_conn()
    alert = _make_alert()
    with conn:
        upsert_alert(conn, alert, [])
    row = conn.execute("SELECT * FROM alerts WHERE id=1").fetchone()
    assert row is not None
    assert row["reference"] == "SR/00001/26"
    conn.close()


def test_upsert_update(tmp_db: Path) -> None:
    import backend.app.db as db_mod
    from scraper.ingest import upsert_alert

    conn = db_mod.get_conn()
    alert = _make_alert()
    with conn:
        upsert_alert(conn, alert, [])
    alert["product_name"] = "Updated Toy"
    with conn:
        upsert_alert(conn, alert, [])
    row = conn.execute("SELECT * FROM alerts WHERE id=1").fetchone()
    assert row["product_name"] == "Updated Toy"
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 1
    conn.close()


def test_upsert_with_photos(tmp_db: Path) -> None:
    import backend.app.db as db_mod
    from scraper.ingest import upsert_alert

    conn = db_mod.get_conn()
    alert = _make_alert()
    photos = [
        {"id": 100, "fileName": "front.jpg", "mainPicture": True},
        {"id": 101, "fileName": "back.jpg", "mainPicture": False},
    ]
    with conn:
        upsert_alert(conn, alert, photos)
    rows = conn.execute("SELECT * FROM photos WHERE alert_id=1").fetchall()
    assert len(rows) == 2
    main = next(r for r in rows if r["main_picture"])
    assert main["filename"] == "front.jpg"
    conn.close()


def test_upsert_replaces_photos(tmp_db: Path) -> None:
    import backend.app.db as db_mod
    from scraper.ingest import upsert_alert

    conn = db_mod.get_conn()
    alert = _make_alert()
    with conn:
        upsert_alert(conn, alert, [{"id": 100, "fileName": "old.jpg", "mainPicture": True}])
    with conn:
        upsert_alert(conn, alert, [{"id": 200, "fileName": "new.jpg", "mainPicture": True}])
    rows = conn.execute("SELECT * FROM photos WHERE alert_id=1").fetchall()
    assert len(rows) == 1
    assert rows[0]["filename"] == "new.jpg"
    conn.close()


def test_fts_search(tmp_db: Path) -> None:
    import backend.app.db as db_mod
    from scraper.ingest import upsert_alert

    conn = db_mod.get_conn()
    alert = _make_alert()
    with conn:
        upsert_alert(conn, alert, [])
    rows = conn.execute(
        "SELECT a.id FROM alerts a JOIN alerts_fts f ON a.id=f.rowid WHERE alerts_fts MATCH 'BrandA'"
    ).fetchall()
    assert len(rows) == 1
    conn.close()
