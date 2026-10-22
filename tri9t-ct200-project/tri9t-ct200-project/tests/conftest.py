import os, tempfile
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/ct200_traceability_test.db")
os.environ.setdefault("GENERATIONS_FILE", "/tmp/ct200_traceability_test_generations.json")
import pytest
from fastapi.testclient import TestClient
from app.database import Base, engine
from app.main import app, store

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    store.path.write_text("[]", encoding="utf-8")
    yield

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture
def data_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "data"
