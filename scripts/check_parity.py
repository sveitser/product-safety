#!/usr/bin/env python3
"""Python ↔ browser embedding parity check.

Embeds a few fixed photos with the active model spec and compares against
vectors produced in the browser (docs/dev-parity.html dumps a JSON blob).
Cosine < 0.99 almost always means a preprocessing mismatch (resize filter,
crop policy, normalization constants) rather than model weights.

Usage:
  python scripts/check_parity.py print            # show reference vectors
  python scripts/check_parity.py compare dump.json
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from embed_lib import ACTIVE_SPEC, MODEL_SPECS, Encoder, load_image_bytes, open_image

IMAGES_DIR = Path("data/images")
ALERTS_DIR = Path("docs/data/alerts")
N_PHOTOS = 5
THRESHOLD = 0.99


def reference_photos() -> list[dict]:
    """First N photos by photo_id across the committed alert files."""
    photos = []
    for f in sorted(ALERTS_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        a = json.loads(f.read_text())
        photos.extend({"photo_id": p["photo_id"]} for p in a["photos"])
    return sorted(photos, key=lambda p: p["photo_id"])[:N_PHOTOS]


def embed_references(spec_name: str) -> dict[int, np.ndarray]:
    encoder = Encoder(spec_name)
    out = {}
    for p in reference_photos():
        img = open_image(load_image_bytes(p, IMAGES_DIR))
        out[p["photo_id"]] = encoder.encode([img])[0]
    return out


def cmd_print(args) -> None:
    for pid, vec in embed_references(args.spec).items():
        print(f"{pid}: {base64.b64encode(vec.tobytes()).decode()}")


def cmd_compare(args) -> None:
    """Compare against a browser dump: {"<photo_id>": "<base64 float32>", ...}."""
    dump = json.loads(Path(args.dump).read_text())
    refs = embed_references(args.spec)
    failed = False
    for pid, vec in refs.items():
        b64 = dump.get(str(pid))
        if b64 is None:
            print(f"{pid}: MISSING from browser dump")
            failed = True
            continue
        browser = np.frombuffer(base64.b64decode(b64), dtype="<f4")
        if browser.shape != vec.shape:
            print(f"{pid}: DIM MISMATCH browser={browser.shape} python={vec.shape}")
            failed = True
            continue
        cos = float(vec @ browser / (np.linalg.norm(browser) or 1.0))
        status = "ok" if cos >= THRESHOLD else "FAIL"
        print(f"{pid}: cosine {cos:.5f} [{status}]")
        failed |= cos < THRESHOLD
    sys.exit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=ACTIVE_SPEC, choices=sorted(MODEL_SPECS))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("print", help="print reference vectors (base64 float32)")
    p.set_defaults(func=cmd_print)
    p = sub.add_parser("compare", help="compare browser dump JSON against Python")
    p.add_argument("dump")
    p.set_defaults(func=cmd_compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
