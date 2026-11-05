"""Engine and session setup. Tables come from create_all; there are no migrations by design."""

from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def make_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def session_factory_for(app: FastAPI) -> sessionmaker[Session]:
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        factory = make_session_factory(get_settings().database_url)
        app.state.session_factory = factory
    return factory


async def get_db(request: Request) -> AsyncIterator[Session]:
    """Routes are async and share the event loop, so DB segments between awaits never interleave.

    Always commit before awaiting PayPal or the LLM: no transaction may stay open across a call.
    """
    with session_factory_for(request.app)() as db:
        yield db
