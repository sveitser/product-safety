import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _insert_alert(conn, **overrides: object) -> int:
    alert = {
        "id": overrides.get("id", 1),
        "reference": overrides.get("reference", "SR/00001/26"),
        "publication_date": "2026-01-01T00:00:00Z",
        "modification_date": "2026-01-01T00:00:00Z",
        "country": overrides.get("country", "Germany"),
        "product_category": overrides.get("product_category", "TOYS"),
        "product_name": overrides.get("product_name", "Toy Car"),
        "product_name_specific": "Red toy car",
        "brands": json.dumps(["BrandX"]),
        "model_types": json.dumps(["Car-01"]),
        "risk_types": json.dumps(["CHOKING"]),
        "risk_description": "Small parts risk.",
        "legal_provision": "GPSD",
        "measures": json.dumps(["RECALL"]),
        "country_of_origin": "China",
        "sold_online": "NO",
        "notification_type": "ARTICLE_12",
        "raw_json": "{}",
    }
    alert.update(overrides)
    cols = ", ".join(alert.keys())
    placeholders = ", ".join("?" for _ in alert)
    conn.execute(f"INSERT INTO alerts ({cols}) VALUES ({placeholders})", list(alert.values()))
    conn.commit()
    return int(alert["id"])


def test_index_empty(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "0 alerts found" in resp.text


def test_index_shows_alerts(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn)
    conn.close()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Toy Car" in resp.text


def test_index_category_filter(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn, id=1, product_name="Toy A", product_category="TOYS")
    _insert_alert(conn, id=2, product_name="Gadget B", product_category="GADGETS")
    conn.close()

    resp = client.get("/?category=TOYS")
    assert "Toy A" in resp.text
    assert "Gadget B" not in resp.text


def test_index_fts_search(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn, id=1, product_name="BrandX Racer")
    _insert_alert(conn, id=2, product_name="Other Thing", brands=json.dumps(["Acme"]))
    conn.close()

    resp = client.get("/?q=BrandX")
    assert "BrandX Racer" in resp.text
    assert "Other Thing" not in resp.text


def test_index_fts_with_category(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn, id=1, product_name="Toy X", product_category="TOYS")
    _insert_alert(conn, id=2, product_name="Toy X", product_category="GADGETS")
    conn.close()

    resp = client.get("/?q=Toy&category=TOYS")
    assert resp.text.count("Toy X") == 1


def test_index_htmx_partial(client: TestClient) -> None:
    resp = client.get("/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # Partial should not contain the full <html> structure
    assert "<html" not in resp.text


def test_index_pagination(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    for i in range(1, 25):
        _insert_alert(conn, id=i, product_name=f"Toy {i}")
    conn.close()

    resp = client.get("/?page=2")
    assert resp.status_code == 200
    assert "Next" in resp.text or "Prev" in resp.text


def test_detail_found(client: TestClient, tmp_db: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn, id=42, product_name="Duck Toy")
    conn.close()

    resp = client.get("/alert/42")
    assert resp.status_code == 200
    assert "Duck Toy" in resp.text
    assert "SR/00001/26" in resp.text


def test_detail_with_photo(client: TestClient, tmp_db: Path, tmp_path: Path) -> None:
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    _insert_alert(conn, id=10, product_name="Doll")
    conn.execute(
        "INSERT INTO photos (id, alert_id, filename, main_picture, local_path) VALUES (?,?,?,?,?)",
        (500, 10, "doll.jpg", 1, str(tmp_path / "500_doll.jpg")),
    )
    conn.commit()
    conn.close()

    resp = client.get("/alert/10")
    assert resp.status_code == 200
    assert "Doll" in resp.text


def test_detail_not_found(client: TestClient) -> None:
    resp = client.get("/alert/99999")
    assert resp.status_code == 404


def test_row_to_dict_empty_json_field(client: TestClient, tmp_db: Path) -> None:
    """Cover the else branch in _row_to_dict (field is None/empty)."""
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    conn.execute(
        """INSERT INTO alerts
        (id, reference, publication_date, modification_date, country,
         product_category, product_name, product_name_specific,
         brands, model_types, risk_types, risk_description, legal_provision,
         measures, country_of_origin, sold_online, notification_type, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (76, "SR/76/26", "2026-01-01", "2026-01-01", "Spain", "TOYS",
         "No Fields Toy", "specific", None, None, None,
         "risk", "law", None, "China", "NO", "ARTICLE_12", "{}"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "No Fields Toy" in resp.text


def test_row_to_dict_invalid_json(client: TestClient, tmp_db: Path) -> None:
    """Cover the except branch in _row_to_dict for malformed JSON fields."""
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    conn.execute(
        """INSERT INTO alerts
        (id, reference, publication_date, modification_date, country,
         product_category, product_name, product_name_specific,
         brands, model_types, risk_types, risk_description, legal_provision,
         measures, country_of_origin, sold_online, notification_type, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (77, "SR/77/26", "2026-01-01", "2026-01-01", "France", "TOYS",
         "Broken JSON Toy", "specific", "NOT_JSON", "[]", "[]",
         "risk", "law", "[]", "China", "NO", "ARTICLE_12", "{}"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Broken JSON Toy" in resp.text
