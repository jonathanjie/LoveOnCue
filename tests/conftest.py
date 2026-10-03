import os
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from wedding_ops.models import Base
from wedding_ops.clock import DemoClock
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.operations import Operations
from wedding_ops.seed import seed_demo, DEMO_TIME
from wedding_ops.views import Queries

@pytest.fixture
def db(tmp_path):
    url = os.getenv("WEDDINGOPS_TEST_DATABASE_URL")
    if url:
        # The test database is destructive by design. Never silently reuse a production URL.
        parsed = make_url(url)
        if not parsed.drivername.startswith("postgresql") or not (parsed.database or "").endswith("_test") or os.getenv("WEDDINGOPS_ALLOW_TEST_DATABASE_RESET") != "yes":
            pytest.fail("PostgreSQL tests require a dedicated *_test database and explicit WEDDINGOPS_ALLOW_TEST_DATABASE_RESET=yes")
        database = Database(url)
        Base.metadata.drop_all(database.engine)
        with database.engine.begin() as connection:connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    else:
        database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_schema()
    seed_demo(database)
    yield database
    database.close()

@pytest.fixture
def clock():
    return DemoClock(DEMO_TIME)

@pytest.fixture
def settings():
    return Settings(mode="test")

@pytest.fixture
def ops(db, clock):
    return Operations(db, "demo-wedding", clock)

@pytest.fixture
def queries(db, clock):
    return Queries(db, "demo-wedding", clock)
