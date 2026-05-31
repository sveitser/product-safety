from pathlib import Path

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import alerts

DATA_IMAGES = Path("data/images")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    DATA_IMAGES.mkdir(parents=True, exist_ok=True)
    app.mount("/images", StaticFiles(directory=DATA_IMAGES), name="images")
    yield


app = FastAPI(title="Product Safety DB", lifespan=lifespan)
app.include_router(alerts.router)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
