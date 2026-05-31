from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import alerts

app = FastAPI(title="Product Safety DB")

app.include_router(alerts.router)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DATA_IMAGES = Path("data/images")


@app.on_event("startup")
def startup() -> None:
    init_db()
    DATA_IMAGES.mkdir(parents=True, exist_ok=True)
    app.mount("/images", StaticFiles(directory=DATA_IMAGES), name="images")
