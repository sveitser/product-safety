#!/usr/bin/env python3
"""Shared image-embedding logic for export and evaluation.

Single source of truth for model specs, pooling math, and image loading so
that scripts/export_alerts.py and scripts/eval_retrieval.py cannot drift.
The spec name doubles as the embedding "model_version" string written into
exported alert files and bundled metadata.
"""

import io
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

EU_IMAGE_BASE = "https://ec.europa.eu/safety-gate-alerts/public/api/notification/image"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) product-safety-export"
FETCH_INTERVAL = 1.0  # seconds between EU API requests (be polite: 1 req/s)

# The spec used for production export. Changing this requires a full
# --force re-export plus the matching frontend change (see docs/js/embed.js).
# Chosen via scripts/eval_retrieval.py — see docs/EVAL.md.
ACTIVE_SPEC = "siglip2-b16-256"


@dataclass(frozen=True)
class ModelSpec:
    hf_id: str
    pooling: str  # "cls" | "mean" | "clsmean" | "projected" | "open_clip"
    dim: int
    backend: str = "transformers"  # "transformers" | "open_clip"


MODEL_SPECS: dict[str, ModelSpec] = {
    # DINOv2 backbone poolings. cls == pooler_output (the historical export).
    # cls/mean/clsmean share one forward pass; clsmean is the two unit vectors
    # concatenated and renormalized (== concat / sqrt(2)).
    "dinov2-base-cls": ModelSpec("facebook/dinov2-base", "cls", 768),
    "dinov2-base-mean": ModelSpec("facebook/dinov2-base", "mean", 768),
    "dinov2-base-clsmean": ModelSpec("facebook/dinov2-base", "clsmean", 1536),
    # DINOv3 (gated on HF for weights download; ONNX mirror used in-browser is not).
    "dinov3-vitb16-cls": ModelSpec("facebook/dinov3-vitb16-pretrain-lvd1689m", "cls", 768),
    "dinov3-vitb16-clsmean": ModelSpec("facebook/dinov3-vitb16-pretrain-lvd1689m", "clsmean", 1536),
    # Contrastive models: projected image features (get_image_features).
    "siglip2-b16-256": ModelSpec("google/siglip2-base-patch16-256", "projected", 768),
    # open_clip-based product-retrieval model (no official ONNX; eval-only first).
    "marqo-ecommerce-b": ModelSpec(
        "hf-hub:Marqo/marqo-ecommerce-embeddings-B", "open_clip", 768, backend="open_clip"
    ),
    "mobileclip2-s2": ModelSpec("MobileCLIP2-S2", "open_clip", 512, backend="open_clip"),
}

# Pretrained tag needed by open_clip for models not hosted as hf-hub checkpoints.
OPEN_CLIP_PRETRAINED = {"MobileCLIP2-S2": "dfndr2b"}


def l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=-1, keepdims=True)
    return arr / np.clip(norms, 1e-12, None)


class Encoder:
    """Embeds PIL images into L2-normalized float32 vectors per a ModelSpec.

    ``image_size`` overrides the processor's default resolution (transformers
    backend only); useful for evaluating DINOv2 at 392/518.
    """

    def __init__(self, spec_name: str, image_size: int | None = None):
        self.spec_name = spec_name
        self.spec = MODEL_SPECS[spec_name]
        self.image_size = image_size
        if self.spec.backend == "open_clip":
            self._init_open_clip()
        else:
            self._init_transformers()

    def _init_transformers(self) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained(self.spec.hf_id)
        self.model = AutoModel.from_pretrained(self.spec.hf_id)
        self.model.eval()
        if self.image_size is not None:
            self._override_size(self.image_size)

    def _override_size(self, size: int) -> None:
        """Scale the resize/crop pipeline to a target crop of ``size`` px."""
        proc = self.processor
        if getattr(proc, "crop_size", None):
            # resize-shortest-edge-then-center-crop pipeline (DINOv2):
            # keep the resize/crop ratio (256/224) of the default config.
            edge = proc.size.get("shortest_edge")
            crop = proc.crop_size["height"]
            ratio = edge / crop if edge else 1.0
            proc.size = {"shortest_edge": round(size * ratio)}
            proc.crop_size = {"height": size, "width": size}
        else:
            # fixed square resize pipeline (SigLIP)
            proc.size = {"height": size, "width": size}

    def _init_open_clip(self) -> None:
        import open_clip
        import torch

        self._torch = torch
        pretrained = OPEN_CLIP_PRETRAINED.get(self.spec.hf_id)
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            self.spec.hf_id, pretrained=pretrained
        )
        self.model.eval()

    def features(self, images: list[Image.Image]) -> dict[str, np.ndarray]:
        """Raw normalized feature views, each (N, d) float32.

        DINO backbones return {"cls", "mean"} (one forward pass serves the
        cls/mean/clsmean specs); contrastive models return {"emb"}.
        """
        torch = self._torch
        if self.spec.backend == "open_clip":
            batch = torch.stack([self.preprocess(im) for im in images])
            with torch.no_grad():
                feats = self.model.encode_image(batch)
            return {"emb": l2_normalize(feats.cpu().numpy().astype("<f4"))}

        inputs = self.processor(images=images, return_tensors="pt")
        with torch.no_grad():
            if self.spec.pooling == "projected":
                # AutoModel may load the full multimodal model (e.g. SiglipModel with
                # vision + text towers); call only the vision sub-model so pixel_values
                # alone is sufficient.
                vision = getattr(self.model, "vision_model", self.model)
                out = vision(pixel_values=inputs["pixel_values"])
                feats = (
                    out.pooler_output
                    if (hasattr(out, "pooler_output") and out.pooler_output is not None)
                    else out.last_hidden_state[:, 0]
                )
                return {"emb": l2_normalize(feats.cpu().numpy().astype("<f4"))}
            out = self.model(**inputs)
        lh = out.last_hidden_state
        # patch tokens start after CLS plus any register tokens (DINOv3 has 4)
        skip = 1 + getattr(self.model.config, "num_register_tokens", 0)
        cls = lh[:, 0].cpu().numpy().astype("<f4")
        mean = lh[:, skip:].mean(dim=1).cpu().numpy().astype("<f4")
        return {"cls": l2_normalize(cls), "mean": l2_normalize(mean)}

    @staticmethod
    def compose(feats: dict[str, np.ndarray], pooling: str) -> np.ndarray:
        """Build the final L2-normalized embedding from feature views.

        For clsmean: each half is unit-norm, so the concat has norm sqrt(2);
        the final normalize gives equal weight to both views. The browser
        (docs/js/embed.js) must mirror this order exactly.
        """
        if pooling in ("projected", "open_clip"):
            return feats["emb"]
        if pooling in ("cls", "mean"):
            return feats[pooling]
        if pooling == "clsmean":
            return l2_normalize(np.concatenate([feats["cls"], feats["mean"]], axis=-1))
        raise ValueError(f"unknown pooling: {pooling}")

    def encode(self, images: list[Image.Image]) -> np.ndarray:
        """(N, dim) L2-normalized float32 embeddings."""
        return self.compose(self.features(images), self.spec.pooling)


def open_image(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


_last_fetch = 0.0


def fetch_image_bytes(photo_id: int, timeout: int = 30) -> bytes:
    """Fetch a photo from the EU API, rate-limited to FETCH_INTERVAL."""
    global _last_fetch
    wait = _last_fetch + FETCH_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(f"{EU_IMAGE_BASE}/{photo_id}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    finally:
        _last_fetch = time.monotonic()


def load_image_bytes(photo: dict, images_dir: Path) -> bytes:
    """Local file if present, else fetch from the EU API and cache locally.

    ``photo`` needs ``photo_id`` and may carry ``local_path`` (scraper layout).
    """
    candidates = [images_dir / f"{photo['photo_id']}.jpg"]
    if photo.get("local_path"):
        candidates.append(images_dir / Path(photo["local_path"]).name)
    for local in candidates:
        if local.exists():
            return local.read_bytes()
    data = fetch_image_bytes(photo["photo_id"])
    images_dir.mkdir(parents=True, exist_ok=True)
    candidates[0].write_bytes(data)
    return data
