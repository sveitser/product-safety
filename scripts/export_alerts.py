#!/usr/bin/env python3
import argparse
import base64
import json
import sqlite3
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPProcessor, CLIPVisionModelWithProjection

DB_PATH = Path("data/safety.db")
IMAGES_DIR = Path("data/images")
OUT_DIR = Path("docs/data/alerts")
MODEL_ID = "openai/clip-vit-base-patch32"

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


def encode_photo(path: Path, processor: CLIPProcessor, model: CLIPVisionModelWithProjection) -> str:
    image = Image.open(path).convert("RGB")
    inputs = processor(images=[image], return_tensors="pt")
    with torch.no_grad():
        feats = model(pixel_values=inputs["pixel_values"]).image_embeds
        feats = F.normalize(feats, p=2, dim=-1)
    arr = feats[0].cpu().numpy().astype("<f4")
    return base64.b64encode(arr.tobytes()).decode()


def write_alert_file(
    out_dir: Path,
    alert: dict,
    images_dir: Path,
    processor: CLIPProcessor,
    model: CLIPVisionModelWithProjection,
) -> None:
    photos = []
    for p in alert["photos"]:
        entry = {"photo_id": p["photo_id"], "main": p["main"]}
        if p["local_path"]:
            img_path = images_dir / Path(p["local_path"]).name
            try:
                entry["embedding"] = encode_photo(img_path, processor, model)
            except Exception as e:
                print(f"  [warn] photo {p['photo_id']}: {e}")
        photos.append(entry)

    record = {k: v for k, v in alert.items() if k != "photos"}
    record["photos"] = photos
    (out_dir / f"{alert['id']}.json").write_text(json.dumps(record, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--images-dir", type=Path, default=IMAGES_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--force", action="store_true", help="recompute existing alert files")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    alerts = load_alerts(args.db)
    todo = [a for a in alerts if args.force or not (args.out / f"{a['id']}.json").exists()]
    print(f"{len(alerts)} alerts in DB, {len(todo)} to export")
    if not todo:
        return

    print(f"loading CLIP model {MODEL_ID}")
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model = CLIPVisionModelWithProjection.from_pretrained(MODEL_ID)
    model.eval()

    for i, alert in enumerate(todo, 1):
        write_alert_file(args.out, alert, args.images_dir, processor, model)
        if i % 50 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} alerts exported")

    print(f"wrote {len(todo)} files → {args.out}")


if __name__ == "__main__":
    main()
