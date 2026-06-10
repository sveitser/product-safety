# Image Retrieval Evaluation

Photo search quality is measured with `scripts/eval_retrieval.py` (see
`just eval-retrieval`). Setup:

- **Split**: for each alert with ≥2 photos, one non-main photo is held out as
  the query (highest photo_id, deterministic); the gallery keeps every other
  photo of all alerts. 639 queries / 1,898 gallery photos as of 2026-06-10.
- **Phone-photo simulation**: each query is evaluated clean plus three seeded
  augmented variants — `clutter` (product composited onto a procedural
  background + lighting jitter), `framing` (perspective + random crop + blur),
  and `phone` (everything combined). All variants end with a downscale + JPEG
  re-encode.
- **Metrics**: alert-level (after the same max-similarity dedupe the frontend
  applies): recall@k, median rank, MRR. The headline number is **augmented
  recall@5** — "is the right product in the top results for a realistic
  phone photo".

## Model comparison (2026-06-10, seed 42)

| run | spec | tta | clean R@1 | R@5 | R@10 | aug R@1 | R@5 | R@10 | aug med-rank |
|---|---|---|---|---|---|---|---|---|---|
| **siglip2-tta (shipped)** | siglip2-b16-256 | center-crop | 0.524 | 0.716 | 0.752 | 0.381 | 0.565 | 0.633 | 3 |
| siglip2 | siglip2-b16-256 | - | 0.520 | 0.718 | 0.770 | 0.366 | 0.549 | 0.620 | 4 |
| marqo-b | marqo-ecommerce-b | - | 0.504 | 0.682 | 0.752 | 0.383 | 0.555 | 0.626 | 3 |
| baseline | dinov2-base-cls | - | 0.408 | 0.563 | 0.628 | 0.324 | 0.492 | 0.564 | 6 |
| dinov2-clsmean | dinov2-base-clsmean | - | 0.406 | 0.551 | 0.615 | 0.311 | 0.471 | 0.540 | 7 |
| dinov2-mean | dinov2-base-mean | - | 0.375 | 0.515 | 0.564 | 0.191 | 0.325 | 0.409 | 23 |

Historical note: CLIP ViT-B/32 (the first model) was replaced by DINOv2-base in
commit 02cec74 (clean R@1 0.39 → 0.44 on an earlier ad-hoc eval).

## Decisions

- **Shipped: `siglip2-b16-256` + center-crop TTA.** +15 pts clean R@5 and
  +7 pts augmented R@5 over the previous production model (dinov2-base-cls),
  with a *smaller* browser download. Contrastively trained models beat DINO
  self-supervised features decisively on this task; DINOv2 pooling variants
  (mean, cls+mean) were dead ends — CLS was already its best pooling.
- **Marqo-ecommerce-B rejected**: edges SigLIP2 by only 0.6 pts augmented
  R@5 — far below the ≥5 pt bar set to justify its manual ONNX export and
  self-hosting (it publishes no ONNX).
- **Browser dtype: fp16 (177 MB)**, verified bit-parity with Python at
  cosine ≥ 0.9998 (Node + onnxruntime, PIL-matched resize in
  `docs/js/embed.js`). int8/uint8 quantizations of this tower are broken
  (cosine ≈ 0.70 vs fp32 on identical input); q4 lands at 0.94 — both
  below the 0.99 parity bar. The fp16 graph needs
  `graphOptimizationLevel: 'basic'` (onnxruntime's extended-level
  SimplifiedLayerNormFusion corrupts it).
- **Preprocessing parity matters more than it looks**: default
  transformers.js resize (sharp/canvas) vs PIL drifts whole-pipeline cosine
  to 0.88–0.97, which silently degrades retrieval. `docs/js/embed.js`
  implements Pillow's antialiased bilinear resize exactly (max pixel diff
  < 1 LSB), restoring cosine to ≥ 0.9998.

## Reproducing

```sh
# inside `nix develop .#ml` (or uv run --with torch --with torchvision \
#   --with transformers --with pillow --with numpy)
python scripts/eval_retrieval.py run --spec siglip2-b16-256 --tta center-crop
python scripts/eval_retrieval.py compare tmp/eval_runs/*.json
python scripts/check_parity.py print          # Python reference vectors
# browser side: open docs/dev-parity.html, drop data/images/<photo_id>.jpg,
# save the JSON dump, then:
python scripts/check_parity.py compare dump.json
```

Augmented query images can be inspected with
`python scripts/eval_retrieval.py dump-queries --out tmp/queries`.
