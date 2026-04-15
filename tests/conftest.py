import asyncio
import os
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
async def postgres_container():
    c = PostgresContainer(
        image="postgres:16-alpine",
        username="test_user",
        password="test_password",
        dbname="test_db",
    )
    c.start()
    yield c
    c.stop()


@pytest.fixture(scope="session")
async def rabbitmq_container():
    c = RabbitMqContainer()
    c.start()
    yield c
    c.stop()


@pytest.fixture
async def async_engine(postgres_container):
    sync_url = postgres_container.get_connection_url()
    url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql+psycopg://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(url, echo=False, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    Session = async_sessionmaker(async_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture
def client(async_session) -> AsyncClient:
    async def _override():
        yield async_session

    app.dependency_overrides[get_session] = _override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
