# Product Safety DB — Agent Guidelines

## Working Style (IMPORTANT)

- **Do not ask questions.** Work non-interactively. Make reasonable decisions.
- **If input is needed from the human**, create a GitHub issue describing the blocker and continue with what can be done.
- **If a tool is missing**, use `nix-shell -p <tool>` rather than stopping.
- **Commit and push after each meaningful chunk of work.** Close GitHub issues as they are resolved (use `closes #N` in commit messages).
- **Git commits**: use `git -c commit.gpgsign=false commit` — the global config has a broken SSH signing key.
- **Push via HTTPS token**: remote URL must be `https://sveitser:${GH_TOKEN}@github.com/sveitser/product-safety.git`. The token is in `.env`.
- Watch token consumption; prefer small focused edits over large rewrites.
- **After finishing each task**, run `gh issue list --repo sveitser/product-safety` and pick up the next open issue.

## Project Goal

Build a better-UX database and search interface for EU Safety Gate product safety alerts.
The official site (https://ec.europa.eu/safety-gate-alerts/screen/search) has poor search UX.
We want intelligent text search, browsable categories, image-based search, and fast filtering.
Initial scope: **toys category only** (expand to all categories later).

## Architecture

```
scraper/          Python async scraper — fetches from Safety Gate public API
backend/          FastAPI + SQLite — REST API + server-rendered HTMX frontend
assets/           Downloaded product images (JPEG)
flake.nix         Nix development environment
```

### Backend stack
- **Language**: Python 3.12
- **Web framework**: FastAPI with Jinja2 + HTMX (server-rendered, minimal JS)
- **Database**: SQLite via sqlite-utils / SQLAlchemy Core (easy to swap later)
- **Full-text search**: SQLite FTS5
- **Image search**: planned — embedding-based (CLIP or similar), out of scope v1

### Scraper strategy
- Source: Safety Gate public API (`https://ec.europa.eu/safety-gate-alerts/`)
- Primary endpoint: `POST /public/api/notification/mostRecent/` (paginates recent alerts)
- Detail endpoint: `GET /public/api/notification/{id}?language=en`
- Images: `GET /public/api/notification/image/{photoId}` → store on filesystem
- Run once daily via systemd timer or cron
- Historical backfill: see issue #5

## Data Model (core fields)

| Field | Source |
|-------|--------|
| id | notification.id |
| reference | notification.reference (e.g. SR/01572/26) |
| publication_date | notification.publicationDate |
| country | notification.country.name |
| product_category | notification.product.productCategory.name |
| product_name | notification.product.versions[EN].name |
| product_name_specific | notification.product.nameSpecific |
| brand | notification.product.brands[].brand |
| model_type | notification.product.modelTypes[].modelType |
| risk_types | notification.risk.riskType[].name |
| risk_description | notification.risk.versions[EN].riskDescription |
| measures | notification.measureTaken.measures[].measureCategory.name |
| country_of_origin | notification.traceability.countryOrigin.name |
| photos | notification.product.photos[].id (stored locally) |

## Key Constraints

- Rate-limit scraper: 1 request/second max, respect robots.txt
- Store raw JSON alongside normalized data (for reprocessing)
- SQLite file at `data/safety.db`, images at `data/images/`
- No authentication or user accounts in v1
- API must serve paginated results; frontend must work without JS enabled (HTMX graceful degradation)

## Commands

```bash
nix develop                          # enter dev shell (installs pre-commit hooks)
python scraper/ingest.py             # scrape TOYS alerts
uvicorn backend.app.main:app --reload  # serve at localhost:8000

# Testing
pytest                               # run all tests
pytest --cov=backend --cov=scraper --cov-report=term-missing   # with coverage
pytest --cov=backend --cov=scraper --cov-report=term-missing 2>&1 | grep -v '100%'  # show uncovered lines only

# Linting / formatting (also run automatically as pre-commit hooks)
ruff check --fix .
ruff format .
ty check
```

## What NOT to do

- Do not use TypeScript/React/Vue unless there is a compelling reason — prefer HTMX
- Do not over-engineer; SQLite is sufficient until it isn't
- Do not commit the SQLite database or scraped data to git
