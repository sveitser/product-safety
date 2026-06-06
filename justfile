# Product Safety — convenience commands
# Run `just` or `just --list` to see available recipes

# Start the uvicorn dev server
dev *args:
    uvicorn backend.app.main:app --reload --port 4455 {{args}}

# Run the scraper
scrape *args:
    python scraper/ingest.py {{args}}

# Run tests
test *args:
    pytest {{args}}

# Run tests with coverage report
coverage *args:
    pytest --cov=backend --cov=scraper --cov-report=term-missing {{args}}

# Run ruff linter and formatter
lint *args:
    ruff check --fix . {{args}}
    ruff format . {{args}}

# Run type checker
typecheck *args:
    ty check {{args}}

# Apply all pending database migrations
migrate *args:
    alembic upgrade head {{args}}

# Compute CLIP embeddings for all product photos (needs `nix develop .#ml` deps)
build-embeddings *args:
    nix --extra-experimental-features 'nix-command flakes' develop .#ml --command python scripts/compute_embeddings.py {{args}}

# Serve the static photo search frontend locally
serve-frontend:
    python -m http.server 8080 --directory docs

# Run lint + typecheck + test in sequence (CI pipeline)
ci: lint typecheck test
