#!/usr/bin/env python3
import argparse
import base64
import json
from collections import Counter
from pathlib import Path

SRC_DIR = Path("docs/data/alerts")
OUT_DIR = Path("docs/data")
EU_IMAGE_BASE = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/image"


def read_alert_files(src: Path) -> list[dict]:
    files = sorted(src.glob("*.json"), key=lambda p: int(p.stem))
    return [json.loads(f.read_text()) for f in files]


# Fields kept out of the initial landing-page bundle to keep first paint fast.
# `risk_description`/`model_types` are search-only and shipped separately in
# alerts-search.json (lazy-loaded); the rest are unused by the frontend.
_BUNDLE_DROP = frozenset(
    {
        "photos",
        "embedding_model",
        "embedding_dim",
        "risk_description",
        "model_types",
        "legal_provision",
        "modification_date",
        "sold_online",
        "notification_type",
        "measures",
    }
)
# Extra search fields lazy-loaded only when the user searches.
_SEARCH_EXTRA = ("risk_description", "model_types")


def build_bundle(alerts: list[dict]) -> dict:
    items = []
    categories = set()
    for a in alerts:
        if a.get("product_category"):
            categories.add(a["product_category"])
        item = {k: v for k, v in a.items() if k not in _BUNDLE_DROP}
        item["photos"] = [{"photo_id": p["photo_id"], "main": p["main"]} for p in a["photos"]]
        items.append(item)
    items.sort(key=lambda x: x.get("publication_date") or "", reverse=True)
    return {"count": len(items), "categories": sorted(categories), "items": items}


def build_search_index(alerts: list[dict]) -> dict:
    """Search-only fields, keyed by id, merged into the MiniSearch index on the
    client the first time a user searches. Keeps these (notably the bulky risk
    descriptions) off the initial landing-page payload."""
    items = [{"id": a["id"], **{k: a.get(k) for k in _SEARCH_EXTRA if a.get(k)}} for a in alerts]
    return {"count": len(items), "fields": list(_SEARCH_EXTRA), "items": items}


def embedding_version(alerts: list[dict]) -> tuple[str, int]:
    """Model version + dim shared by all alert files; fail hard on a mix.

    A mixed bundle (partial re-export) would silently corrupt similarity
    scores, so refuse to build one.
    """
    versions = Counter(
        (a.get("embedding_model") or "unknown", a.get("embedding_dim") or 768)
        for a in alerts
        if any("embedding" in p for p in a["photos"])
    )
    if len(versions) > 1:
        detail = ", ".join(f"{model}/{dim}: {n} alerts" for (model, dim), n in versions.items())
        raise SystemExit(f"mixed embedding versions, re-export with --force first ({detail})")
    (model, dim), _ = versions.most_common(1)[0]
    return model, dim


def build_embeddings(alerts: list[dict]) -> tuple[bytes, dict]:
    model, dim = embedding_version(alerts)
    blob = bytearray()
    meta = []
    for a in alerts:
        for p in sorted(a["photos"], key=lambda x: x["photo_id"]):
            if "embedding" not in p:
                continue
            raw = base64.b64decode(p["embedding"])
            if len(raw) != dim * 4:
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
    return bytes(blob), {
        "count": len(meta),
        "dim": dim,
        "model_version": model,
        "dtype": "float32",
        "items": meta,
    }


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

    search_index = build_search_index(alerts)
    (args.out / "alerts-search.json").write_text(json.dumps(search_index, ensure_ascii=False))
    search_kb = (args.out / "alerts-search.json").stat().st_size // 1024
    print(f"saved alerts-search.json ({search_index['count']} alerts, {search_kb} KB)")

    blob, meta = build_embeddings(alerts)
    (args.out / "embeddings.bin").write_bytes(blob)
    (args.out / "metadata.json").write_text(json.dumps(meta))
    print(
        f"saved embeddings.bin + metadata.json "
        f"({meta['count']} photos, {meta['model_version']}/{meta['dim']}d, {len(blob) // 1024} KB)"
    )


if __name__ == "__main__":
    main()
