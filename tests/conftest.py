import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_TMP_DIR = Path("E:/python_files/rebuild_agent/.tmp")
TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(TEST_TMP_DIR))
os.environ.setdefault("TEMP", str(TEST_TMP_DIR))


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/rebuild_agent_test",
)

from conf.db_conf import get_db
from main import app


async def _fake_db_session():
    yield None


@pytest.fixture(autouse=True)
def override_dependencies():
    previous_debug = app.debug
    app.debug = False
    app.dependency_overrides[get_db] = _fake_db_session
    yield
    app.debug = previous_debug
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_output_dir():
    output_dir = TEST_TMP_DIR / "pytest-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    yield output_dir
