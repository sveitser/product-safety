# Product Safety — convenience commands
# Run `just` or `just --list` to see available recipes

# Start the uvicorn dev server
dev:
    uvicorn backend.app.main:app --reload

# Run the scraper
scrape:
    python scraper/ingest.py

# Run tests
test:
    pytest

# Run tests with coverage report
coverage:
    pytest --cov=backend --cov=scraper --cov-report=term-missing

# Run ruff linter and formatter
lint:
    ruff check --fix .
    ruff format .

# Run type checker
typecheck:
    ty check

# Apply all pending database migrations
migrate:
    alembic upgrade head

# Run lint + typecheck + test in sequence (CI pipeline)
ci: lint typecheck test
