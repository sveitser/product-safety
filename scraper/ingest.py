"""
Safety Gate scraper — fetches alerts from the EU Safety Gate public API.

Endpoints used:
  POST /public/api/notification/mostRecent/  → paginated recent alerts
  GET  /public/api/notification/{id}?language=en → full detail
  GET  /public/api/notification/image/{photoId}  → JPEG image

Run:
  python scraper/ingest.py                     # fetch TOYS category (default)
  python scraper/ingest.py --all-categories    # fetch all product categories
  python scraper/ingest.py --category TOYS     # fetch a specific category
  python scraper/ingest.py --max-pages 2       # limit pages fetched
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.app.db import get_conn, init_db

BASE_URL = "https://ec.europa.eu/safety-gate-alerts"
IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "data/images"))
REQUEST_DELAY = 1.0  # seconds between requests


HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "language": "en",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}


def extract_alert(detail: dict[str, Any]) -> dict[str, Any]:
    """Flatten a full notification detail JSON into a DB row dict."""
    product = detail.get("product") or {}
    risk = detail.get("risk") or {}
    measures_obj = detail.get("measureTaken") or {}
    traceability = detail.get("traceability") or {}

    # English version of product
    prod_versions = product.get("versions") or []
    prod_en = next(
        (v for v in prod_versions if (v.get("language") or {}).get("key") == "EN"),
        prod_versions[0] if prod_versions else {},
    )

    # English version of risk
    risk_versions = risk.get("versions") or []
    risk_en = next(
        (v for v in risk_versions if (v.get("language") or {}).get("key") == "EN"),
        risk_versions[0] if risk_versions else {},
    )

    brands = [b["brand"] for b in (product.get("brands") or []) if b.get("brand")]
    model_types = [m["modelType"] for m in (product.get("modelTypes") or []) if m.get("modelType")]
    risk_types = [r["name"] for r in (risk.get("riskType") or []) if r.get("name")]
    measures = [
        m.get("measureCategory", {}).get("name", "")
        for m in (measures_obj.get("measures") or [])
        if m.get("measureCategory")
    ]

    country_obj = detail.get("country") or {}
    product_cat = (product.get("productCategory") or {}).get("name", "")
    country_origin = (traceability.get("countryOrigin") or {}).get("name", "")
    sold_online_obj = traceability.get("isSoldOnline") or {}
    notif_type = (detail.get("notificationType") or {}).get("name", "")

    return {
        "id": detail["id"],
        "reference": detail.get("reference", ""),
        "publication_date": detail.get("publicationDate", ""),
        "modification_date": detail.get("modificationDate", ""),
        "country": country_obj.get("name", ""),
        "product_category": product_cat,
        "product_name": prod_en.get("name", ""),
        "product_name_specific": product.get("nameSpecific", ""),
        "brands": json.dumps(brands),
        "model_types": json.dumps(model_types),
        "risk_types": json.dumps(risk_types),
        "risk_description": risk_en.get("riskDescription", ""),
        "legal_provision": risk_en.get("legalProvision", ""),
        "measures": json.dumps(measures),
        "country_of_origin": country_origin,
        "sold_online": sold_online_obj.get("name", ""),
        "notification_type": notif_type,
        "raw_json": json.dumps(detail),
    }


def upsert_alert(
    conn: sqlite3.Connection, alert_row: dict[str, Any], photos: list[dict[str, Any]]
) -> None:
    cols = list(alert_row.keys())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO alerts ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        list(alert_row.values()),
    )
    # Delete old photos for this alert and re-insert
    conn.execute("DELETE FROM photos WHERE alert_id=?", (alert_row["id"],))
    for photo in photos:
        conn.execute(
            "INSERT INTO photos (id, alert_id, filename, main_picture) VALUES (?,?,?,?)",
            (photo["id"], alert_row["id"], photo["fileName"], int(photo.get("mainPicture", False))),
        )


async def download_image(client: httpx.AsyncClient, photo_id: int, filename: str) -> Path | None:
    dest = IMAGES_DIR / f"{photo_id}_{filename}"
    if dest.exists():
        return dest
    try:
        resp = await client.get(f"{BASE_URL}/public/api/notification/image/{photo_id}")
        if resp.status_code == 200:
            dest.write_bytes(resp.content)
            return dest
    except Exception as e:
        print(f"  [warn] image {photo_id}: {e}")
    return None


async def fetch_detail(client: httpx.AsyncClient, alert_id: int) -> dict | None:
    try:
        resp = await client.get(
            f"{BASE_URL}/public/api/notification/{alert_id}",
            params={"language": "en"},
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [warn] detail {alert_id}: {e}")
    return None


async def fetch_page(client: httpx.AsyncClient, page: int, category: str) -> dict | None:
    body: dict = {"language": "en", "page": str(page)}
    if category and category != "ALL":
        body["productCategory"] = category
    try:
        resp = await client.post(f"{BASE_URL}/public/api/notification/mostRecent/", json=body)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [warn] page {page}: {e}")
    return None


async def run(category: str = "TOYS", max_pages: int = 999, download_images: bool = True) -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    conn = get_conn()

    cat_label = "ALL categories" if category == "ALL" else f"category={category}"
    print(f"Starting ingestion ({cat_label}, max_pages={max_pages})")

    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        page = 0
        total_processed = 0

        while page < max_pages:
            print(f"Fetching page {page} ({cat_label})…")
            data = await fetch_page(client, page, category)

            if data is None:
                print("  Failed to fetch page, stopping.")
                break

            content = data.get("content") or []
            total_pages = data.get("totalPages", 1)
            total_elements = data.get("totalElements", 0)

            if page == 0:
                print(f"  Total alerts available: {total_elements} across {total_pages} pages")

            if not content:
                break

            for item in content:
                alert_id = item["id"]
                await asyncio.sleep(REQUEST_DELAY)

                detail = await fetch_detail(client, alert_id)
                if detail is None:
                    print(f"  Skipping {alert_id} — no detail")
                    continue

                photos = (detail.get("product") or {}).get("photos") or []
                alert_row = extract_alert(detail)

                with conn:
                    upsert_alert(conn, alert_row, photos)

                if download_images:
                    for photo in photos:
                        await asyncio.sleep(0.5)
                        local_path = await download_image(client, photo["id"], photo["fileName"])
                        if local_path:
                            with conn:
                                conn.execute(
                                    "UPDATE photos SET local_path=? WHERE id=?",
                                    (str(local_path), photo["id"]),
                                )

                total_processed += 1
                ref = detail.get("reference", alert_id)
                name = alert_row.get("product_name") or alert_row.get("product_name_specific", "")
                print(f"  [{total_processed}/{total_elements}] {ref} — {name}")

            page += 1
            if page >= total_pages:
                break

            print(f"  Fetched page {page - 1}, total so far: {total_processed} alerts")
            await asyncio.sleep(REQUEST_DELAY)

    conn.close()
    print(f"\nDone. Processed {total_processed} alerts.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest Safety Gate alerts")
    parser.add_argument(
        "--category",
        default="TOYS",
        help="Product category filter (default: TOYS). Use ALL to fetch all categories.",
    )
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Fetch all product categories (equivalent to --category ALL)",
    )
    parser.add_argument("--max-pages", type=int, default=999, help="Max pages to fetch")
    parser.add_argument("--no-images", action="store_true", help="Skip image downloads")
    args = parser.parse_args()

    category = "ALL" if args.all_categories else args.category

    asyncio.run(
        run(
            category=category,
            max_pages=args.max_pages,
            download_images=not args.no_images,
        )
    )
