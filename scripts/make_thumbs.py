#!/usr/bin/env python3
"""Generate self-hosted WebP thumbnails for the search-page cards.

The frontend cards only render at ~240px, but the EU Safety Gate image API
serves full-resolution JPEGs (~175 KB each) from a slow, rate-limiting origin
with no CDN. Loading 20 of those at once on the search grid is slow and, worse,
the origin load-sheds by returning intermittent 404s — so working images
randomly show "No image". Serving small thumbnails from our own GitHub Pages
CDN fixes both: ~3.7 KB WebP instead of ~175 KB, and no dependency on the flaky
origin (the live EU URL stays as the card's onerror fallback).

One thumbnail is produced per alert that has a photo, using its main photo
(falling back to the first). Generation is incremental and resumable: a
photo whose ``{photo_id}.webp`` already exists is skipped without a network
request, so the daily scrape can backfill a bounded slice each run via
``--limit`` and keep up with new alerts thereafter.

Usage:
  python scripts/make_thumbs.py                 # fill every missing thumbnail
  python scripts/make_thumbs.py --limit 800     # cap work this run (CI)
  python scripts/make_thumbs.py --size 240 --quality 72
"""

import argparse
import asyncio
import io
import json
from pathlib import Path

import httpx
from PIL import Image

SRC_DIR = Path("docs/data/alerts")
OUT_DIR = Path("docs/data/thumbs")
EU_IMAGE_BASE = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/image"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}


def main_photo_id(alert: dict) -> int | None:
    """The photo shown on a card: the main one, else the first, else none."""
    photos = alert.get("photos") or []
    if not photos:
        return None
    main = next((p for p in photos if p.get("main")), photos[0])
    return main["photo_id"]


def needed_photo_ids(src: Path, out: Path) -> list[int]:
    """Card photo_ids (one per alert with a photo) that lack a thumbnail yet."""
    ids: list[int] = []
    seen: set[int] = set()
    for f in sorted(src.glob("*.json"), key=lambda p: int(p.stem)):
        pid = main_photo_id(json.loads(f.read_text()))
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        if not (out / f"{pid}.webp").exists():
            ids.append(pid)
    return ids


def to_thumb(image_bytes: bytes, size: int, quality: int) -> bytes:
    """Resize to fit a ``size``×``size`` box and encode as WebP."""
    im = Image.open(io.BytesIO(image_bytes))
    im = im.convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


async def fetch_and_write(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    photo_id: int,
    out: Path,
    size: int,
    quality: int,
    delay: float,
) -> bool:
    dest = out / f"{photo_id}.webp"
    async with sem:
        try:
            resp = await client.get(f"{EU_IMAGE_BASE}/{photo_id}")
            # The origin returns 404 both for genuinely-missing images and as a
            # load-shedding response; either way there is nothing to thumbnail.
            if resp.status_code != 200 or not resp.content:
                return False
            dest.write_bytes(to_thumb(resp.content, size, quality))
            return True
        except Exception as e:
            print(f"  [warn] photo {photo_id}: {type(e).__name__}: {e}")
            return False
        finally:
            await asyncio.sleep(delay)


async def run(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    ids = needed_photo_ids(args.src, args.out)
    total_missing = len(ids)
    if args.limit:
        ids = ids[: args.limit]
    print(f"{total_missing} thumbnails missing; generating {len(ids)} this run")
    if not ids:
        return

    sem = asyncio.Semaphore(args.concurrency)
    made = 0
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=httpx.Timeout(60.0, connect=10.0)
    ) as client:
        wave = 200
        for i in range(0, len(ids), wave):
            chunk = ids[i : i + wave]
            results = await asyncio.gather(
                *(
                    fetch_and_write(client, sem, pid, args.out, args.size, args.quality, args.delay)
                    for pid in chunk
                )
            )
            made += sum(results)
            print(f"  processed {i + len(chunk)}/{len(ids)} — {made} thumbnails written")

    print(f"\nDone. Wrote {made} thumbnails to {args.out} ({total_missing - made} still missing).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=SRC_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--size", type=int, default=240, help="Bounding box in px (default 240)")
    parser.add_argument("--quality", type=int, default=72, help="WebP quality (default 72)")
    parser.add_argument("--limit", type=int, default=0, help="Max thumbnails this run (0 = all)")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent downloads")
    parser.add_argument("--delay", type=float, default=0.3, help="Per-request delay (politeness)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
