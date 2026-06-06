#!/usr/bin/env python3
import argparse
import base64
import json
from pathlib import Path

SRC_DIR = Path("docs/data/alerts")
OUT_DIR = Path("docs/data")
EU_IMAGE_BASE = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/image"
DIM = 512


def read_alert_files(src: Path) -> list[dict]:
    files = sorted(src.glob("*.json"), key=lambda p: int(p.stem))
    return [json.loads(f.read_text()) for f in files]


def build_bundle(alerts: list[dict]) -> dict:
    items = []
    categories = set()
    for a in alerts:
        if a.get("product_category"):
            categories.add(a["product_category"])
        item = {k: v for k, v in a.items() if k != "photos"}
        item["photos"] = [{"photo_id": p["photo_id"], "main": p["main"]} for p in a["photos"]]
        items.append(item)
    items.sort(key=lambda x: x.get("publication_date") or "", reverse=True)
    return {"count": len(items), "categories": sorted(categories), "items": items}


def build_embeddings(alerts: list[dict]) -> tuple[bytes, dict]:
    blob = bytearray()
    meta = []
    for a in alerts:
        for p in sorted(a["photos"], key=lambda x: x["photo_id"]):
            if "embedding" not in p:
                continue
            raw = base64.b64decode(p["embedding"])
            if len(raw) != DIM * 4:
                print(f"  [warn] photo {p['photo_id']}: bad embedding length {len(raw)}")
                continue
            meta.append(
                {
                    "idx": len(meta),
                    "photo_id": p["photo_id"],
                    "alert_id": a["id"],
                    "reference": a.get("reference", ""),
                    "product_name": a.get("product_name") or "",
                    "category": a.get("product_category") or "",
                    "image_url": f"{EU_IMAGE_BASE}/{p['photo_id']}",
                }
            )
            blob.extend(raw)
    return bytes(blob), {"count": len(meta), "dim": DIM, "items": meta}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=SRC_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    alerts = read_alert_files(args.src)
    print(f"{len(alerts)} alert files read")

    bundle = build_bundle(alerts)
    (args.out / "alerts-bundle.json").write_text(json.dumps(bundle, ensure_ascii=False))
    bundle_kb = (args.out / "alerts-bundle.json").stat().st_size // 1024
    print(f"saved alerts-bundle.json ({bundle['count']} alerts, {bundle_kb} KB)")

    blob, meta = build_embeddings(alerts)
    (args.out / "embeddings.bin").write_bytes(blob)
    (args.out / "metadata.json").write_text(json.dumps(meta))
    print(f"saved embeddings.bin + metadata.json ({meta['count']} photos, {len(blob) // 1024} KB)")


if __name__ == "__main__":
    main()
