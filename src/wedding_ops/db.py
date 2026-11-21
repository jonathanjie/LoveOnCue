"""Short database units of work; never hold a transaction across network I/O."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, Wedding
from .errors import missing


class Database:
    def __init__(self, url: str):
        options: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            parsed = make_url(url)
            if parsed.database and parsed.database != ":memory:":
                Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
            options["connect_args"] = {"check_same_thread": False, "timeout": 15}
            if parsed.database in {None, "", ":memory:"}:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.sqlite = self.engine.dialect.name == "sqlite"
        if self.sqlite:
            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=15000")
                cursor.close()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, autoflush=True)

    def create_schema(self) -> None:
        """For demo/tests only. Production migrations use Alembic."""
        with self.engine.begin() as connection:
            if self.sqlite:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            Base.metadata.create_all(connection)
            if self.sqlite:
                schema = inspect(connection)
                # Older local demos used create_all without an Alembic revision.
                if (not schema.has_table("alembic_version")
                        and all(column["name"] != "telegram_draft_id" for column in schema.get_columns("notifications"))):
                    connection.exec_driver_sql("ALTER TABLE notifications ADD COLUMN telegram_draft_id VARCHAR(64)")

    @contextmanager
    def transaction(self, wedding_id: str, *, write: bool = False) -> Iterator[tuple[Session, Wedding]]:
        with self.sessions() as session:
            try:
                if self.sqlite:
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
                query = select(Wedding).where(Wedding.id == wedding_id)
                if not self.sqlite:
                    query = query.with_for_update(read=not write)
                wedding = session.scalar(query)
                if wedding is None:
                    raise missing()
                yield session, wedding
                session.commit()
            except Exception:
                session.rollback()
                raise

    def close(self) -> None:
        self.engine.dispose()
