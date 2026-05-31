import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FULL_DETAIL: dict[str, Any] = {
    "id": 42,
    "reference": "SR/00042/26",
    "publicationDate": "2026-03-15T10:00:00Z",
    "modificationDate": "2026-03-16T00:00:00Z",
    "notificationType": {"key": "k", "code": "A12", "name": "ARTICLE_12"},
    "country": {"key": "DE", "name": "Germany"},
    "product": {
        "productCategory": {"key": "product.category.toys", "name": "TOYS"},
        "nameSpecific": "Plastic Duck",
        "brands": [{"brand": "DuckCo"}],
        "modelTypes": [{"modelType": "DK-01"}],
        "versions": [
            {
                "language": {"key": "EN", "name": "english"},
                "name": "Bath Duck",
                "description": "Yellow rubber duck",
                "packageDescription": "Cardboard box",
            }
        ],
        "photos": [{"id": 9001, "fileName": "duck.jpg", "mainPicture": True}],
    },
    "risk": {
        "riskType": [{"key": "riskType.choking", "name": "CHOKING"}],
        "versions": [
            {
                "language": {"key": "EN", "name": "english"},
                "riskDescription": "Small parts detach under force.",
                "legalProvision": "GPSD Article 5",
            }
        ],
    },
    "measureTaken": {
        "measures": [
            {
                "measureCategory": {"key": "measure.category.recall", "name": "RECALL"},
                "measureType": {"key": "measure.type.voluntary", "name": "VOLUNTARY"},
            }
        ],
        "companyRecalls": [],
    },
    "traceability": {
        "countryOrigin": {"key": "CN", "name": "People's Republic of China"},
        "isSoldOnline": {"key": "option.yes", "name": "YES"},
    },
}


def test_extract_alert_basic() -> None:
    from scraper.ingest import extract_alert

    row = extract_alert(FULL_DETAIL)
    assert row["id"] == 42
    assert row["reference"] == "SR/00042/26"
    assert row["product_name"] == "Bath Duck"
    assert row["product_name_specific"] == "Plastic Duck"
    assert json.loads(row["brands"]) == ["DuckCo"]
    assert json.loads(row["model_types"]) == ["DK-01"]
    assert json.loads(row["risk_types"]) == ["CHOKING"]
    assert row["risk_description"] == "Small parts detach under force."
    assert row["legal_provision"] == "GPSD Article 5"
    assert json.loads(row["measures"]) == ["RECALL"]
    assert row["country"] == "Germany"
    assert row["country_of_origin"] == "People's Republic of China"
    assert row["sold_online"] == "YES"
    assert row["notification_type"] == "ARTICLE_12"
    assert row["product_category"] == "TOYS"


def test_extract_alert_missing_english_falls_back() -> None:
    from scraper.ingest import extract_alert

    detail = dict(FULL_DETAIL)
    product = dict(detail["product"])
    product["versions"] = [
        {
            "language": {"key": "DE"},
            "name": "Badespielzeug",
            "description": "",
            "packageDescription": "",
        }
    ]
    detail["product"] = product
    row = extract_alert(detail)
    assert row["product_name"] == "Badespielzeug"


def test_extract_alert_empty_optionals() -> None:
    from scraper.ingest import extract_alert

    minimal = {
        "id": 1,
        "reference": "SR/00001/26",
        "publicationDate": None,
        "modificationDate": None,
        "notificationType": None,
        "country": None,
        "product": None,
        "risk": None,
        "measureTaken": None,
        "traceability": None,
    }
    row = extract_alert(minimal)
    assert row["id"] == 1
    assert row["brands"] == "[]"
    assert row["risk_types"] == "[]"
    assert row["country"] == ""


def test_extract_alert_raw_json_stored() -> None:
    from scraper.ingest import extract_alert

    row = extract_alert(FULL_DETAIL)
    parsed = json.loads(row["raw_json"])
    assert parsed["id"] == 42


@pytest.mark.asyncio
async def test_fetch_page_success(tmp_path: Path) -> None:
    from scraper.ingest import fetch_page

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [], "totalPages": 1, "totalElements": 0}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await fetch_page(mock_client, 0, "TOYS")
    assert result is not None
    assert result["totalPages"] == 1
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_page_all_category() -> None:
    from scraper.ingest import fetch_page

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [], "totalPages": 1, "totalElements": 0}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await fetch_page(mock_client, 0, "ALL")
    assert result is not None
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "productCategory" not in body


@pytest.mark.asyncio
async def test_fetch_page_error() -> None:
    from scraper.ingest import fetch_page

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network error")

    result = await fetch_page(mock_client, 0, "TOYS")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_page_non_200() -> None:
    from scraper.ingest import fetch_page

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await fetch_page(mock_client, 0, "TOYS")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_detail_success() -> None:
    from scraper.ingest import fetch_detail

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = FULL_DETAIL

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    result = await fetch_detail(mock_client, 42)
    assert result == FULL_DETAIL


@pytest.mark.asyncio
async def test_fetch_detail_error() -> None:
    from scraper.ingest import fetch_detail

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("timeout")

    result = await fetch_detail(mock_client, 42)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_detail_non_200() -> None:
    from scraper.ingest import fetch_detail

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    result = await fetch_detail(mock_client, 42)
    assert result is None


@pytest.mark.asyncio
async def test_download_image_success(tmp_path: Path) -> None:
    from scraper import ingest

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"JPEG_DATA"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch.object(ingest, "IMAGES_DIR", tmp_path):
        result = await ingest.download_image(mock_client, 9001, "duck.jpg")

    assert result is not None
    assert result.read_bytes() == b"JPEG_DATA"


@pytest.mark.asyncio
async def test_download_image_already_exists(tmp_path: Path) -> None:
    from scraper import ingest

    existing = tmp_path / "9001_duck.jpg"
    existing.write_bytes(b"CACHED")

    mock_client = AsyncMock()

    with patch.object(ingest, "IMAGES_DIR", tmp_path):
        result = await ingest.download_image(mock_client, 9001, "duck.jpg")

    assert result == existing
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_download_image_error(tmp_path: Path) -> None:
    from scraper import ingest

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("timeout")

    with patch.object(ingest, "IMAGES_DIR", tmp_path):
        result = await ingest.download_image(mock_client, 9001, "duck.jpg")

    assert result is None


@pytest.mark.asyncio
async def test_run_full(tmp_db: Path, tmp_path: Path) -> None:
    import backend.app.db as db_mod
    from scraper import ingest

    page_resp = {
        "content": [{"id": 42}],
        "totalPages": 1,
        "totalElements": 1,
        "number": 0,
        "pageSize": 100,
    }

    mock_page_resp = MagicMock()
    mock_page_resp.status_code = 200
    mock_page_resp.json.return_value = page_resp

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    mock_img_resp.content = b"IMG"

    async def mock_get(url, **kwargs):
        if "image" in url:
            return mock_img_resp
        return mock_detail_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_page_resp
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="TOYS", max_pages=1, download_images=True)

    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=42").fetchone()
    assert row is not None
    assert row["product_name"] == "Bath Duck"
    conn.close()


@pytest.mark.asyncio
async def test_run_skips_missing_detail(tmp_db: Path, tmp_path: Path) -> None:
    import backend.app.db as db_mod
    from scraper import ingest

    page_resp = {
        "content": [{"id": 99}],
        "totalPages": 1,
        "totalElements": 1,
        "number": 0,
        "pageSize": 100,
    }

    mock_page_resp = MagicMock()
    mock_page_resp.status_code = 200
    mock_page_resp.json.return_value = page_resp

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_page_resp
    mock_client.get.return_value = mock_detail_resp

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="TOYS", max_pages=1, download_images=False)

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 0
    conn.close()


@pytest.mark.asyncio
async def test_run_empty_content_stops(tmp_db: Path, tmp_path: Path) -> None:
    """Cover the `if not content: break` branch."""
    from scraper import ingest

    page_resp = {
        "content": [],
        "totalPages": 3,
        "totalElements": 0,
        "number": 0,
        "pageSize": 100,
    }

    mock_page_resp = MagicMock()
    mock_page_resp.status_code = 200
    mock_page_resp.json.return_value = page_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_page_resp

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="TOYS", max_pages=5, download_images=False)

    # Only one page fetch attempted before empty content breaks the loop
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_run_multi_page(tmp_db: Path, tmp_path: Path) -> None:
    """Cover the inter-page sleep (line after `page += 1`)."""
    import backend.app.db as db_mod
    from scraper import ingest

    detail_a = {
        **FULL_DETAIL,
        "id": 1,
        "reference": "SR/00001/26",
        "product": {
            **FULL_DETAIL["product"],
            "photos": [{"id": 9001, "fileName": "a.jpg", "mainPicture": True}],
        },
    }
    detail_b = {
        **FULL_DETAIL,
        "id": 2,
        "reference": "SR/00002/26",
        "product": {
            **FULL_DETAIL["product"],
            "photos": [{"id": 9002, "fileName": "b.jpg", "mainPicture": True}],
        },
    }

    def page_response(alert_id: int, total_pages: int, page_num: int) -> dict:
        return {
            "content": [{"id": alert_id}],
            "totalPages": total_pages,
            "totalElements": 2,
            "number": page_num,
            "pageSize": 1,
        }

    call_count = {"n": 0}

    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        n = call_count["n"]
        call_count["n"] += 1
        resp.json.return_value = page_response(n + 1, 2, n)
        return resp

    detail_resps = {1: detail_a, 2: detail_b}

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        if "image" in url:
            resp.status_code = 200
            resp.content = b"IMG"
        else:
            alert_id = int(url.rstrip("/").split("/")[-1])
            resp.status_code = 200
            resp.json.return_value = detail_resps.get(alert_id, FULL_DETAIL)
        return resp

    mock_client = AsyncMock()
    mock_client.post.side_effect = mock_post
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="TOYS", max_pages=5, download_images=False)

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 2
    conn.close()


@pytest.mark.asyncio
async def test_run_stops_on_failed_page(tmp_db: Path, tmp_path: Path) -> None:
    from scraper import ingest

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network failure")

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="TOYS", max_pages=5, download_images=False)


@pytest.mark.asyncio
async def test_run_all_categories(tmp_db: Path, tmp_path: Path) -> None:
    """category='ALL' omits productCategory filter and uses 'ALL categories' label."""
    import backend.app.db as db_mod
    from scraper import ingest

    page_resp = {
        "content": [{"id": 42}],
        "totalPages": 1,
        "totalElements": 1,
        "number": 0,
        "pageSize": 100,
    }

    mock_page_resp = MagicMock()
    mock_page_resp.status_code = 200
    mock_page_resp.json.return_value = page_resp

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    async def mock_get(url, **kwargs):
        return mock_detail_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_page_resp
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run(category="ALL", max_pages=1, download_images=False)

    # Verify no productCategory in the POST body
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "productCategory" not in body

    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=42").fetchone()
    assert row is not None
    conn.close()


# ---------------------------------------------------------------------------
# Tests for historical ingestion via webreport/all
# ---------------------------------------------------------------------------

WEBREPORT_PAGE: dict = {
    "content": [
        {
            "id": 9001,
            "code": "Report-2024-01",
            "publicationDate": "2024-01-10T00:00:00.000+00:00",
            "notifications": [
                {"id": 42, "reference": "A12/00042/24"},
            ],
        }
    ],
    "totalElements": 1,
    "totalPages": 1,
    "size": 10,
    "number": 0,
    "empty": False,
}


@pytest.mark.asyncio
async def test_fetch_webreport_years_success() -> None:
    from scraper.ingest import fetch_webreport_years

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [2026, 2025, 2024]

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    result = await fetch_webreport_years(mock_client)
    assert result == [2026, 2025, 2024]


@pytest.mark.asyncio
async def test_fetch_webreport_years_error() -> None:
    from scraper.ingest import fetch_webreport_years

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("timeout")

    result = await fetch_webreport_years(mock_client)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_webreport_years_non_200() -> None:
    from scraper.ingest import fetch_webreport_years

    mock_resp = MagicMock()
    mock_resp.status_code = 460

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    result = await fetch_webreport_years(mock_client)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_webreport_page_success() -> None:
    from scraper.ingest import fetch_webreport_page

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = WEBREPORT_PAGE

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await fetch_webreport_page(mock_client, 2024, 0)
    assert result is not None
    assert result["totalPages"] == 1
    mock_client.post.assert_called_once()
    call_body = mock_client.post.call_args.kwargs["json"]
    assert call_body["year"] == 2024
    assert call_body["page"] == "0"


@pytest.mark.asyncio
async def test_fetch_webreport_page_error() -> None:
    from scraper.ingest import fetch_webreport_page

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network error")

    result = await fetch_webreport_page(mock_client, 2024, 0)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_webreport_page_non_200() -> None:
    from scraper.ingest import fetch_webreport_page

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await fetch_webreport_page(mock_client, 2024, 0)
    assert result is None


@pytest.mark.asyncio
async def test_run_historical_basic(tmp_db: Path, tmp_path: Path) -> None:
    """run_historical fetches webreport pages then fetches detail for each ID."""
    import backend.app.db as db_mod
    from scraper import ingest

    mock_webreport_resp = MagicMock()
    mock_webreport_resp.status_code = 200
    mock_webreport_resp.json.return_value = WEBREPORT_PAGE

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    async def mock_post(url, **kwargs):
        return mock_webreport_resp

    async def mock_get(url, **kwargs):
        return mock_detail_resp

    mock_client = AsyncMock()
    mock_client.post.side_effect = mock_post
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=[2024], download_images=False)

    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=42").fetchone()
    assert row is not None
    assert row["product_name"] == "Bath Duck"
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_deduplicates_ids(tmp_db: Path, tmp_path: Path) -> None:
    """Notification IDs that appear in multiple reports are only fetched once."""
    import backend.app.db as db_mod
    from scraper import ingest

    # Two reports, both referencing the same notification ID
    wr_page = {
        "content": [
            {"id": 9001, "code": "Report-2024-01", "notifications": [{"id": 42}]},
            {"id": 9002, "code": "Report-2024-02", "notifications": [{"id": 42}]},
        ],
        "totalElements": 2,
        "totalPages": 1,
        "size": 10,
        "number": 0,
    }

    mock_webreport_resp = MagicMock()
    mock_webreport_resp.status_code = 200
    mock_webreport_resp.json.return_value = wr_page

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_webreport_resp
    mock_client.get.return_value = mock_detail_resp

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=[2024], download_images=False)

    # Detail should be fetched exactly once despite the ID appearing twice
    get_calls = [c for c in mock_client.get.call_args_list if "image" not in str(c)]
    assert len(get_calls) == 1

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 1
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_skips_missing_detail(tmp_db: Path, tmp_path: Path) -> None:
    from scraper import ingest

    mock_webreport_resp = MagicMock()
    mock_webreport_resp.status_code = 200
    mock_webreport_resp.json.return_value = WEBREPORT_PAGE

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_webreport_resp
    mock_client.get.return_value = mock_detail_resp

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=[2024], download_images=False)

    # Alert with 404 detail should not be inserted
    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 0
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_failed_webreport_page(tmp_db: Path, tmp_path: Path) -> None:
    """A failed webreport page fetch is skipped gracefully."""
    from scraper import ingest

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("network failure")

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=[2024], download_images=False)

    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 0
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_no_years(tmp_db: Path, tmp_path: Path) -> None:
    """When year listing fails, run_historical exits without crashing."""
    from scraper import ingest

    mock_years_resp = MagicMock()
    mock_years_resp.status_code = 460  # non-200

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_years_resp

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        # years=None triggers the automatic year listing
        await ingest.run_historical(years=None, download_images=False)

    import backend.app.db as db_mod

    conn = db_mod.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 0
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_with_images(tmp_db: Path, tmp_path: Path) -> None:
    """run_historical downloads images when download_images=True."""
    import backend.app.db as db_mod
    from scraper import ingest

    mock_webreport_resp = MagicMock()
    mock_webreport_resp.status_code = 200
    mock_webreport_resp.json.return_value = WEBREPORT_PAGE

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    mock_img_resp.content = b"IMG"

    async def mock_get(url, **kwargs):
        if "image" in url:
            return mock_img_resp
        return mock_detail_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_webreport_resp
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=[2024], download_images=True)

    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=42").fetchone()
    assert row is not None
    # Image file should exist
    img_files = list(tmp_path.glob("9001_*.jpg"))
    assert len(img_files) == 1
    conn.close()


@pytest.mark.asyncio
async def test_run_historical_auto_years(tmp_db: Path, tmp_path: Path) -> None:
    """When years=None, historical run fetches year list then processes each year."""
    import backend.app.db as db_mod
    from scraper import ingest

    mock_years_resp = MagicMock()
    mock_years_resp.status_code = 200
    mock_years_resp.json.return_value = [2024]

    mock_webreport_resp = MagicMock()
    mock_webreport_resp.status_code = 200
    mock_webreport_resp.json.return_value = WEBREPORT_PAGE

    mock_detail_resp = MagicMock()
    mock_detail_resp.status_code = 200
    mock_detail_resp.json.return_value = FULL_DETAIL

    async def mock_get(url, **kwargs):
        if "years" in url:
            return mock_years_resp
        return mock_detail_resp

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_webreport_resp
    mock_client.get.side_effect = mock_get

    with (
        patch("scraper.ingest.IMAGES_DIR", tmp_path),
        patch("scraper.ingest.REQUEST_DELAY", 0),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ingest.run_historical(years=None, download_images=False)

    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM alerts WHERE id=42").fetchone()
    assert row is not None
    conn.close()
