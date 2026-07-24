#!/usr/bin/env python3
import argparse
import base64
import json
import sqlite3
from pathlib import Path

from embed_lib import ACTIVE_SPEC, MODEL_SPECS, Encoder, load_image_bytes, open_image

DB_PATH = Path("data/safety.db")
IMAGES_DIR = Path("data/images")
OUT_DIR = Path("docs/data/alerts")

ALERT_FIELDS = [
    "id",
    "reference",
    "publication_date",
    "modification_date",
    "country",
    "product_category",
    "product_name",
    "product_name_specific",
    "risk_description",
    "legal_provision",
    "country_of_origin",
    "sold_online",
    "notification_type",
]
JSON_FIELDS = ["brands", "model_types", "risk_types", "measures"]


def load_alerts(db: Path) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    alerts = []
    for row in conn.execute("SELECT * FROM alerts ORDER BY id").fetchall():
        d = {f: row[f] for f in ALERT_FIELDS}
        for f in JSON_FIELDS:
            raw = row[f]
            d[f] = json.loads(raw) if raw else []
        photos = conn.execute(
            "SELECT id, main_picture, local_path FROM photos "
            "WHERE alert_id=? ORDER BY main_picture DESC, id",
            (row["id"],),
        ).fetchall()
        d["photos"] = [
            {"photo_id": p["id"], "main": bool(p["main_picture"]), "local_path": p["local_path"]}
            for p in photos
        ]
        alerts.append(d)
    conn.close()
    return alerts


def load_alerts_from_files(src: Path) -> list[dict]:
    """Rebuild alert records from previously exported per-alert JSONs.

    Enables a full re-export (e.g. after a model change) without the scraper
    DB: all alert fields are carried over and embeddings are recomputed.
    """
    alerts = []
    for f in sorted(src.glob("*.json"), key=lambda p: int(p.stem)):
        a = json.loads(f.read_text())
        a.pop("embedding_model", None)
        a.pop("embedding_dim", None)
        a["photos"] = [{"photo_id": p["photo_id"], "main": p["main"]} for p in a["photos"]]
        alerts.append(a)
    return alerts


def _needs_export(alert: dict, out_dir: Path) -> bool:
    """Whether ``alert`` must be (re-)written to ``out_dir``.

    Exports a new alert, and re-exports an existing one whose upstream
    ``modification_date`` has advanced since it was last written — that is how a
    re-published alert (with reassigned photo IDs) gets its photos and embeddings
    refreshed instead of keeping stale, no-longer-resolving image IDs.
    """
    dest = out_dir / f"{alert['id']}.json"
    if not dest.exists():
        return True
    try:
        existing = json.loads(dest.read_text())
    except (OSError, ValueError):
        return True
    return alert.get("modification_date") != existing.get("modification_date")


def encode_photo(image_bytes: bytes, encoder: Encoder) -> str:
    arr = encoder.encode([open_image(image_bytes)])[0]
    return base64.b64encode(arr.tobytes()).decode()


def write_alert_file(out_dir: Path, alert: dict, images_dir: Path, encoder: Encoder) -> None:
    photos = []
    for p in alert["photos"]:
        entry = {"photo_id": p["photo_id"], "main": p["main"]}
        try:
            entry["embedding"] = encode_photo(load_image_bytes(p, images_dir), encoder)
        except Exception as e:
            print(f"  [warn] photo {p['photo_id']}: {e}")
        photos.append(entry)

    record = {k: v for k, v in alert.items() if k != "photos"}
    record["embedding_model"] = encoder.spec_name
    record["embedding_dim"] = encoder.spec.dim
    record["photos"] = photos
    (out_dir / f"{alert['id']}.json").write_text(json.dumps(record, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--images-dir", type=Path, default=IMAGES_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--spec", default=ACTIVE_SPEC, choices=sorted(MODEL_SPECS))
    parser.add_argument("--force", action="store_true", help="recompute existing alert files")
    parser.add_argument(
        "--from-files",
        action="store_true",
        help="re-export from existing per-alert JSONs instead of the scraper DB",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    alerts = load_alerts_from_files(args.out) if args.from_files else load_alerts(args.db)
    todo = [a for a in alerts if args.force or _needs_export(a, args.out)]
    print(f"{len(alerts)} alerts in DB, {len(todo)} to export")
    if not todo:
        return

    print(f"loading model spec {args.spec} ({MODEL_SPECS[args.spec].hf_id})")
    encoder = Encoder(args.spec)

    for i, alert in enumerate(todo, 1):
        write_alert_file(args.out, alert, args.images_dir, encoder)
        if i % 50 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} alerts exported")

    print(f"wrote {len(todo)} files → {args.out}")


if __name__ == "__main__":
    main()
