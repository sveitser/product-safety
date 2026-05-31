from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("IMAGES_DIR", str(tmp_path / "images"))

    import importlib
    import backend.app.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    return db


@pytest.fixture
def client(tmp_db: Path) -> TestClient:
    import importlib
    import backend.app.routers.alerts as routes_mod
    import backend.app.main as main_mod

    importlib.reload(routes_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c
