#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import CLIPProcessor, CLIPVisionModelWithProjection

DB_PATH = Path("data/safety.db")
IMAGES_DIR = Path("data/images")
OUTPUT_DIR = Path("docs/data")
MODEL_ID = "openai/clip-vit-base-patch32"
EU_IMAGE_BASE = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/image"


def load_photos(db: Path) -> list[dict]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.id AS photo_id, p.local_path, p.alert_id,
               a.reference, a.product_name, a.product_category
        FROM photos p
        JOIN alerts a ON a.id = p.alert_id
        WHERE p.local_path IS NOT NULL
        ORDER BY p.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def encode_images(
    paths: list[Path],
    processor: CLIPProcessor,
    model: CLIPVisionModelWithProjection,
    batch_size: int = 32,
) -> list:
    all_embeddings = []
    for i in range(0, len(paths), batch_size):
        batch_paths = paths[i : i + batch_size]
        images = []
        valid_idx = []
        for j, p in enumerate(batch_paths):
            try:
                images.append(Image.open(p).convert("RGB"))
                valid_idx.append(j)
            except Exception as e:
                print(f"  [warn] {p.name}: {e}")

        if not images:
            all_embeddings.extend([None] * len(batch_paths))
            continue

        inputs = processor(images=images, return_tensors="pt")
        with torch.no_grad():
            feats = model(pixel_values=inputs["pixel_values"]).image_embeds
            feats = F.normalize(feats, p=2, dim=-1)

        feat_list = feats.cpu().numpy()
        result = [None] * len(batch_paths)
        for k, idx in enumerate(valid_idx):
            result[idx] = feat_list[k]
        all_embeddings.extend(result)

        done = min(i + batch_size, len(paths))
        print(f"  {done}/{len(paths)} images processed")

    return all_embeddings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--images-dir", type=Path, default=IMAGES_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading CLIP model {MODEL_ID}")
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model = CLIPVisionModelWithProjection.from_pretrained(MODEL_ID)
    model.eval()

    rows = load_photos(args.db)
    print(f"{len(rows)} photos in DB")

    paths = [args.images_dir / Path(r["local_path"]).name for r in rows]
    embeddings_raw = encode_images(paths, processor, model)

    embeddings = []
    metadata = []
    for row, emb in zip(rows, embeddings_raw, strict=True):
        if emb is None:
            continue
        idx = len(embeddings)
        embeddings.append(emb)
        metadata.append(
            {
                "idx": idx,
                "photo_id": row["photo_id"],
                "alert_id": row["alert_id"],
                "reference": row["reference"],
                "product_name": row["product_name"] or "",
                "category": row["product_category"] or "",
                "image_url": f"{EU_IMAGE_BASE}/{row['photo_id']}",
            }
        )

    emb_array = np.array(embeddings, dtype=np.float32)
    bin_path = args.output_dir / "embeddings.bin"
    meta_path = args.output_dir / "metadata.json"

    with open(bin_path, "wb") as f:
        f.write(emb_array.tobytes())

    with open(meta_path, "w") as f:
        json.dump({"count": len(metadata), "dim": 512, "items": metadata}, f)

    kb = bin_path.stat().st_size // 1024
    print(f"saved {len(embeddings)} embeddings → {bin_path} ({kb} KB)")
    print(f"saved metadata → {meta_path}")
    skipped = len(rows) - len(embeddings)
    if skipped:
        print(f"skipped {skipped} photos (missing/unreadable)")


if __name__ == "__main__":
    main()
