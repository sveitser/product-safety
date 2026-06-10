#!/usr/bin/env python3
"""Retrieval evaluation for the photo-search feature.

Splits the committed alert photos (docs/data/alerts/*.json) into held-out
queries and a gallery, simulates phone photos with seeded augmentations, and
reports alert-level retrieval metrics that replicate docs/photo.html ranking
(max similarity per alert). No DB needed; images are read from data/images/
and fetched from the EU API (rate-limited) when missing.

Usage:
  python scripts/eval_retrieval.py run --spec dinov2-base-cls --name baseline
  python scripts/eval_retrieval.py run --spec dinov2-base-clsmean --image-size 392
  python scripts/eval_retrieval.py compare tmp/eval_runs/*.json
  python scripts/eval_retrieval.py dump-queries --out tmp/queries --n 20
"""

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
from embed_lib import MODEL_SPECS, Encoder, l2_normalize, load_image_bytes, open_image

ALERTS_DIR = Path("docs/data/alerts")
IMAGES_DIR = Path("data/images")
CACHE_DIR = Path("tmp/eval_cache")
RUNS_DIR = Path("tmp/eval_runs")

# Named augmentation profiles: each query gets the clean image plus one
# variant per profile. Separate profiles tell us *which* domain gap hurts.
PROFILES = ["clutter", "framing", "phone"]
BATCH_SIZE = 8


# ---------------------------------------------------------------- split


def load_photo_index() -> list[dict]:
    photos = []
    for f in sorted(ALERTS_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        a = json.loads(f.read_text())
        for p in a["photos"]:
            photos.append({"photo_id": p["photo_id"], "alert_id": a["id"], "main": p["main"]})
    return photos


def split_queries(photos: list[dict]) -> tuple[set[int], set[int]]:
    """Deterministic split → (query photo_ids, gallery photo_ids).

    For each alert with >=2 photos, hold out one non-main photo (highest
    photo_id) as the query; the gallery keeps the main/catalog shot. Returns
    explicit photo_id sets so leakage is impossible by construction.
    """
    by_alert: dict[int, list[dict]] = {}
    for p in photos:
        by_alert.setdefault(p["alert_id"], []).append(p)
    queries: set[int] = set()
    for plist in by_alert.values():
        if len(plist) < 2:
            continue
        nonmain = [p for p in plist if not p["main"]] or plist
        queries.add(max(p["photo_id"] for p in nonmain))
    gallery = {p["photo_id"] for p in photos} - queries
    return queries, gallery


# ---------------------------------------------------------------- augmentations


def _make_background(rng: random.Random, size: int) -> Image.Image:
    """Procedural clutter background: blurred noise or flat surface w/ vignette."""
    if rng.random() < 0.5:
        noise = (np.random.default_rng(rng.getrandbits(32)).random((48, 48, 3)) * 255).astype(
            "uint8"
        )
        bg = Image.fromarray(noise).resize((size, size), Image.BICUBIC)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=size / 40))
    else:
        color = tuple(rng.randint(60, 210) for _ in range(3))
        bg = Image.new("RGB", (size, size), color)
    # vignette
    y, x = np.mgrid[0:size, 0:size].astype("float32") / size - 0.5
    vig = 1.0 - 0.6 * (x * x + y * y)
    arr = np.asarray(bg).astype("float32") * vig[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def _composite_clutter(img: Image.Image, rng: random.Random) -> tuple[Image.Image, tuple]:
    """Paste the (rotated, scaled) product onto a clutter background.

    Returns the composite and the product center (cx, cy) in pixels.
    """
    size = 768
    bg = _make_background(rng, size)
    prod = img.convert("RGBA").rotate(rng.uniform(-15, 15), expand=True, resample=Image.BICUBIC)
    scale = rng.uniform(0.5, 0.8) * size / max(prod.size)
    prod = prod.resize((max(1, int(prod.width * scale)), max(1, int(prod.height * scale))))
    px = rng.randint(0, size - prod.width)
    py = rng.randint(0, size - prod.height)
    bg.paste(prod, (px, py), prod)
    return bg, (px + prod.width / 2, py + prod.height / 2)


def _random_crop(img: Image.Image, rng: random.Random, center: tuple | None) -> Image.Image:
    """Random crop of 55-90% area whose window contains the product center."""
    w, h = img.size
    frac = rng.uniform(0.55, 0.90) ** 0.5
    cw, ch = int(w * frac), int(h * frac)
    cx, cy = center if center else (w / 2, h / 2)
    x0 = rng.randint(max(0, int(cx) - cw), min(w - cw, int(cx)))
    y0 = rng.randint(max(0, int(cy) - ch), min(h - ch, int(cy)))
    return img.crop((x0, y0, x0 + cw, y0 + ch))


def _perspective(img: Image.Image, rng: random.Random) -> Image.Image:
    """Corner jitter up to ±8% of the image size."""
    w, h = img.size
    j = 0.08
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [(x + rng.uniform(-j, j) * w, y + rng.uniform(-j, j) * h) for x, y in src]
    # solve projective coeffs mapping output (src) -> input (dst)
    a = []
    b = []
    for (sx, sy), (dx, dy) in zip(src, dst, strict=True):
        a.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        a.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
        b.extend([sx, sy])
    coeffs = np.linalg.solve(np.array(a, dtype="float64"), np.array(b, dtype="float64"))
    # fill the out-of-frame wedges with the mean edge color, not black
    arr = np.asarray(img)
    edges = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    fill = tuple(int(c) for c in edges.mean(axis=0))
    return img.transform((w, h), Image.PERSPECTIVE, tuple(coeffs), Image.BICUBIC, fillcolor=fill)


def _lighting(img: Image.Image, rng: random.Random) -> Image.Image:
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.6, 1.4))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.6, 1.4))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.6, 1.4))
    gains = np.array([rng.uniform(0.9, 1.1) for _ in range(3)], dtype="float32")
    arr = np.asarray(img).astype("float32") * gains
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def _phone_pipeline(img: Image.Image, rng: random.Random) -> Image.Image:
    """Downscale + JPEG re-encode, like a messaging-app photo. Always last."""
    import io

    scale = 800 / max(img.size)
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(45, 75))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def augment(img: Image.Image, profile: str, photo_id: int, seed: int) -> Image.Image:
    rng = random.Random(f"{seed}:{photo_id}:{profile}")
    center = None
    if profile in ("clutter", "phone"):
        img, center = _composite_clutter(img, rng)
        img = _lighting(img, rng)
    if profile in ("framing", "phone"):
        # perspective before crop so the crop trims the warp's border wedges
        img = _perspective(img, rng)
        img = _random_crop(img, rng, center)
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 2.0)))
    return _phone_pipeline(img, rng)


# ---------------------------------------------------------------- embedding cache


def cache_key(spec_name: str, image_size: int | None) -> str:
    spec = MODEL_SPECS[spec_name]
    return f"{spec.hf_id.replace('/', '_').replace(':', '_')}@{image_size or 'def'}"


def embed_with_cache(
    names_images: list[tuple[str, Image.Image | None]],
    spec_name: str,
    image_size: int | None,
    loader,
) -> dict[str, dict[str, np.ndarray]]:
    """Return {name: feature views} embedding only cache misses.

    ``loader(name)`` produces the PIL image for a missing entry (images are
    materialized lazily so cached runs never touch image files).
    """
    cdir = CACHE_DIR / cache_key(spec_name, image_size)
    cdir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, np.ndarray]] = {}
    missing = []
    for name, _ in names_images:
        f = cdir / f"{name}.npz"
        if f.exists():
            with np.load(f) as z:
                out[name] = {k: z[k] for k in z.files}
        else:
            missing.append(name)
    if missing:
        print(f"  embedding {len(missing)} images (cache: {cdir})")
        encoder = Encoder(spec_name, image_size=image_size)
        t0 = time.monotonic()
        for i in range(0, len(missing), BATCH_SIZE):
            chunk = missing[i : i + BATCH_SIZE]
            loaded = []
            valid_names = []
            for n in chunk:
                try:
                    loaded.append(loader(n))
                    valid_names.append(n)
                except Exception as e:
                    print(f"  [skip] {n}: {e}")
            if not loaded:
                continue
            feats = encoder.features(loaded)
            for j, name in enumerate(valid_names):
                views = {k: v[j] for k, v in feats.items()}
                np.savez(cdir / f"{name}.npz", **views)
                out[name] = views
            done = i + len(chunk)
            if done % 200 < BATCH_SIZE or done == len(missing):
                rate = done / (time.monotonic() - t0)
                print(f"    {done}/{len(missing)} ({rate:.1f} img/s)", flush=True)
    return out


# ---------------------------------------------------------------- metrics


def compute_metrics(ranks: list[int]) -> dict:
    return {
        "n": len(ranks),
        "recall@1": round(sum(r <= 1 for r in ranks) / len(ranks), 4),
        "recall@5": round(sum(r <= 5 for r in ranks) / len(ranks), 4),
        "recall@10": round(sum(r <= 10 for r in ranks) / len(ranks), 4),
        "median_rank": statistics.median(ranks),
        "mrr": round(sum(1 / r for r in ranks) / len(ranks), 4),
    }


def alert_rank(scores: np.ndarray, gallery_alerts: np.ndarray, true_alert: int) -> int:
    """Rank of the true alert after per-alert max-sim dedupe (1-based)."""
    order = np.argsort(-scores)
    seen = set()
    rank = 0
    for idx in order:
        aid = int(gallery_alerts[idx])
        if aid in seen:
            continue
        seen.add(aid)
        rank += 1
        if aid == true_alert:
            return rank
    raise ValueError(f"alert {true_alert} not in gallery")


# ---------------------------------------------------------------- run


def make_loader(photo_meta: dict[int, dict], seed: int, tta: str | None):
    """Image loader for cache misses. Names: '{pid}', '{pid}.{profile}', '… .cc80'."""

    def load(name: str) -> Image.Image:
        parts = name.split(".")
        pid = int(parts[0])
        img = open_image(load_image_bytes(photo_meta[pid], IMAGES_DIR))
        mods = parts[1:]
        for profile in PROFILES:
            if profile in mods:
                img = augment(img, profile, pid, seed)
        if "cc80" in mods:
            w, h = img.size
            cw, ch = int(w * 0.8), int(h * 0.8)
            img = img.crop(((w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch))
        return img

    return load


def run(args) -> None:
    spec = MODEL_SPECS[args.spec]
    photos = load_photo_index()
    photo_meta = {p["photo_id"]: p for p in photos}
    query_ids, gallery_ids = split_queries(photos)
    assert not (query_ids & gallery_ids), "query/gallery leak"
    if args.limit:
        query_ids = set(sorted(query_ids)[: args.limit])
    print(
        f"spec={args.spec} size={args.image_size or 'default'} tta={args.tta or 'none'} "
        f"| {len(query_ids)} queries, {len(gallery_ids)} gallery photos"
    )

    loader = make_loader(photo_meta, args.seed, args.tta)
    tta_suffixes = [""] + ([".cc80"] if args.tta == "center-crop" else [])

    # gallery (clean only)
    gallery_names = [str(pid) for pid in sorted(gallery_ids)]
    feats = embed_with_cache([(n, None) for n in gallery_names], args.spec, args.image_size, loader)
    valid_gallery = [n for n in gallery_names if n in feats]
    if len(valid_gallery) < len(gallery_names):
        print(f"  [warn] {len(gallery_names) - len(valid_gallery)} gallery photos skipped")
    gallery_mat = np.stack([Encoder.compose(feats[n], spec.pooling) for n in valid_gallery])
    gallery_alerts = np.array([photo_meta[int(n)]["alert_id"] for n in valid_gallery])

    # queries: clean + one variant per profile, each with optional TTA crops
    variants = [""] + [f".{p}" for p in PROFILES]
    query_names = [
        f"{pid}{v}{t}" for pid in sorted(query_ids) for v in variants for t in tta_suffixes
    ]
    qfeats = embed_with_cache([(n, None) for n in query_names], args.spec, args.image_size, loader)

    ranks: dict[str, list[int]] = {"clean": [], **{p: [] for p in PROFILES}}
    for pid in sorted(query_ids):
        true_alert = photo_meta[pid]["alert_id"]
        for v in variants:
            keys = [f"{pid}{v}{t}" for t in tta_suffixes]
            available = [k for k in keys if k in qfeats]
            if not available:
                continue
            embs = [Encoder.compose(qfeats[k], spec.pooling) for k in available]
            q = l2_normalize(np.mean(embs, axis=0)) if len(embs) > 1 else embs[0]
            r = alert_rank(gallery_mat @ q, gallery_alerts, true_alert)
            ranks["clean" if v == "" else v[1:]].append(r)

    aug_ranks = [r for p in PROFILES for r in ranks[p]]
    metrics = {
        "clean": compute_metrics(ranks["clean"]),
        "augmented": compute_metrics(aug_ranks),
        "per_profile": {p: compute_metrics(ranks[p]) for p in PROFILES},
    }
    result = {
        "name": args.name,
        "spec": args.spec,
        "image_size": args.image_size,
        "tta": args.tta,
        "seed": args.seed,
        "queries": len(query_ids),
        "gallery": len(gallery_ids),
        "metrics": metrics,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{args.name}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(metrics, indent=2))
    print(f"saved {out}")


# ---------------------------------------------------------------- compare


def fmt_row(r: dict) -> str:
    m = r["metrics"]

    def cells(s):
        return f"{s['recall@1']:.3f} | {s['recall@5']:.3f} | {s['recall@10']:.3f}"

    size = r.get("image_size") or "def"
    tta = r.get("tta") or "-"
    return (
        f"| {r['name']} | {r['spec']} | {size} | {tta} | {cells(m['clean'])} | "
        f"{cells(m['augmented'])} | {m['augmented']['median_rank']} |"
    )


def compare(args) -> None:
    runs = [json.loads(Path(f).read_text()) for f in args.runs]
    runs.sort(key=lambda r: -r["metrics"]["augmented"]["recall@5"])
    print(
        "| run | spec | size | tta | clean R@1 | R@5 | R@10 | aug R@1 | R@5 | R@10 | aug med-rank |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        print(fmt_row(r))


# ---------------------------------------------------------------- dump-queries


def dump_queries(args) -> None:
    photos = load_photo_index()
    photo_meta = {p["photo_id"]: p for p in photos}
    query_ids, _ = split_queries(photos)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for pid in sorted(query_ids)[: args.n]:
        img = open_image(load_image_bytes(photo_meta[pid], IMAGES_DIR))
        alert_id = photo_meta[pid]["alert_id"]
        img.save(out / f"{alert_id}_{pid}_clean.jpg", quality=90)
        for profile in PROFILES:
            augment(img, profile, pid, args.seed).save(
                out / f"{alert_id}_{pid}_{profile}.jpg", quality=90
            )
    print(f"wrote {args.n} query sets → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="evaluate one spec")
    p.add_argument("--spec", required=True, choices=sorted(MODEL_SPECS))
    p.add_argument("--image-size", type=int, default=None)
    p.add_argument("--tta", choices=["center-crop"], default=None, dest="tta")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--limit", type=int, default=None, help="cap query count (smoke test)")
    p.add_argument("--name", default=None)
    p.set_defaults(func=run)

    p = sub.add_parser("compare", help="markdown table across runs")
    p.add_argument("runs", nargs="+")
    p.set_defaults(func=compare)

    p = sub.add_parser("dump-queries", help="write query images for manual browser tests")
    p.add_argument("--out", default="tmp/queries")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=dump_queries)

    args = parser.parse_args()
    if getattr(args, "name", None) is None and args.cmd == "run":
        size = f"-{args.image_size}" if args.image_size else ""
        tta = f"-{args.tta}" if args.tta else ""
        args.name = f"{args.spec}{size}{tta}"
    args.func(args)


if __name__ == "__main__":
    main()
