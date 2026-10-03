import pytest
from wedding_ops.clock import DemoClock
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.operations import Operations
from wedding_ops.seed import seed_demo, DEMO_TIME
from wedding_ops.views import Queries

@pytest.fixture
def db(tmp_path):
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
