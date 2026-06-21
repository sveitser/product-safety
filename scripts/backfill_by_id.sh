#!/usr/bin/env bash
# One-time full historical backfill by sweeping the notification-ID space.
#
# For each ID sub-range it: scrapes valid alerts (+images), exports per-alert
# JSON with SigLIP embeddings, then commits & pushes that batch to the current
# branch. Resumable: alerts already in docs/data/alerts are skipped, so empty
# batches produce no commit and re-running continues where it left off.
set -uo pipefail

START="${START:-10000000}"
END="${END:-10100000}"
STEP="${STEP:-2000}"
CONC="${CONC:-6}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

export DB_PATH="${DB_PATH:-data/safety.db}"
export IMAGES_DIR="${IMAGES_DIR:-data/images}"

SCRAPE_DEPS=(--with httpx --with alembic --with sqlalchemy)
EXPORT_DEPS=(--with torch --with torchvision --with transformers --with pillow --with numpy)
UV=(uv run --no-project --python 3.12)

push() {
  for a in 1 2 3 4; do
    git push -u origin "$BRANCH" && return 0
    sleep $((2 ** a))
  done
  echo "  [warn] push failed after retries"
}

echo "Backfill sweep [$START..$END] step=$STEP conc=$CONC branch=$BRANCH"
for (( s=START; s<END; s+=STEP )); do
  e=$(( s + STEP - 1 ))
  echo "=== BATCH $s..$e ==="

  "${UV[@]}" "${SCRAPE_DEPS[@]}" python scraper/ingest.py \
    --id-range "$s" "$e" --known-dir docs/data/alerts --concurrency "$CONC" \
    || echo "  [warn] scrape failed for $s..$e, continuing"

  "${UV[@]}" "${EXPORT_DEPS[@]}" python scripts/export_alerts.py \
    || echo "  [warn] export failed for $s..$e, continuing"

  if [ -n "$(git status --porcelain docs/data/alerts)" ]; then
    n=$(git status --porcelain docs/data/alerts | wc -l)
    git add docs/data/alerts
    git commit -q -F - <<EOF
data: backfill alert ID range $s-$e ($n new/updated)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YKmp5NbktwRmGq5MDvLkGy
EOF
    push
    echo "  committed $n alert(s) for $s..$e"
  else
    echo "  no new alerts in $s..$e"
  fi

  # Embeddings are baked into the JSON; drop downloaded images to save disk.
  rm -rf "$IMAGES_DIR"
done
echo "Backfill sweep complete."
