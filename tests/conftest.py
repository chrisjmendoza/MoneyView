from pathlib import Path

import pytest

from app import create_app
from app.db import get_db


@pytest.fixture
def app(tmp_path: Path):
    database_path = tmp_path / "moneyview-test.sqlite3"
    app = create_app({"TESTING": True, "DATABASE_PATH": database_path})
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def database(app):
    with app.app_context():
        yield get_db()