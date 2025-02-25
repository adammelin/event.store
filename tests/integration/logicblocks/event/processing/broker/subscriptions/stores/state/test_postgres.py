import os
import sys

import pytest
import pytest_asyncio
from psycopg import AsyncConnection, abc, sql
from psycopg_pool import AsyncConnectionPool

from logicblocks.event.db import PostgresConnectionSettings
from logicblocks.event.processing.broker import (
    EventSubscriptionState,
    EventSubscriptionStateChange,
    EventSubscriptionStateChangeType,
    EventSubscriptionStateStore,
    PostgresEventSubscriptionStateStore,
)
from logicblocks.event.testcases import (
    EventSubscriptionStateStoreCases,
)
from logicblocks.event.testing import data
from logicblocks.event.types import CategoryIdentifier

connection_settings = PostgresConnectionSettings(
    user="admin",
    password="super-secret",
    host="localhost",
    port=5432,
    dbname="some-database",
)

project_root = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "..",
        "..",
        "..",
        "..",
        "..",
    )
)


def relative_to_root(*path_parts: str) -> str:
    return os.path.join(project_root, *path_parts)


def create_table_query(table: str) -> abc.Query:
    with open(relative_to_root("sql", "create_subscriptions_table.sql")) as f:
        create_table_sql = f.read().replace("subscriptions", "{0}")

        return create_table_sql.format(table).encode()


def create_indices_query(table: str) -> abc.Query:
    with open(
        relative_to_root("sql", "create_subscriptions_indices.sql")
    ) as f:
        create_indices_sql = f.read().replace("subscriptions", "{0}")

        return create_indices_sql.format(table).encode()


def drop_table_query(table_name: str) -> abc.Query:
    return sql.SQL("DROP TABLE IF EXISTS {0}").format(
        sql.Identifier(table_name)
    )


def truncate_table_query(table_name: str) -> abc.Query:
    return sql.SQL("TRUNCATE {0}").format(sql.Identifier(table_name))


def read_subscriber_states_query(table: str) -> abc.Query:
    return sql.SQL("SELECT * FROM {0} ORDER BY last_seen").format(
        sql.Identifier(table)
    )


async def create_table(
    pool: AsyncConnectionPool[AsyncConnection], table: str
) -> None:
    async with pool.connection() as connection:
        await connection.execute(create_table_query(table))
        await connection.execute(create_indices_query(table))


async def clear_table(
    pool: AsyncConnectionPool[AsyncConnection], table: str
) -> None:
    async with pool.connection() as connection:
        await connection.execute(truncate_table_query(table))


async def drop_table(
    pool: AsyncConnectionPool[AsyncConnection], table: str
) -> None:
    async with pool.connection() as connection:
        await connection.execute(drop_table_query(table))


@pytest_asyncio.fixture
async def open_connection_pool():
    conninfo = connection_settings.to_connection_string()
    pool = AsyncConnectionPool[AsyncConnection](conninfo, open=False)

    await pool.open()

    try:
        yield pool
    finally:
        await pool.close()


class TestPostgresEventSubscriptionStateStore(
    EventSubscriptionStateStoreCases
):
    pool: AsyncConnectionPool[AsyncConnection]

    @pytest_asyncio.fixture(autouse=True)
    async def store_connection_pool(self, open_connection_pool):
        self.pool = open_connection_pool

    @pytest_asyncio.fixture(autouse=True)
    async def reinitialise_storage(self, open_connection_pool):
        await drop_table(open_connection_pool, "subscriptions")
        await create_table(open_connection_pool, "subscriptions")

    def construct_store(self, node_id: str) -> EventSubscriptionStateStore:
        return PostgresEventSubscriptionStateStore(
            node_id=node_id, connection_source=self.pool
        )

    async def test_does_not_partially_apply_changes(self):
        node_id = data.random_node_id()
        store = self.construct_store(node_id=node_id)

        addition = EventSubscriptionStateChange(
            type=EventSubscriptionStateChangeType.ADD,
            subscription=EventSubscriptionState(
                group=data.random_subscriber_group(),
                id=data.random_subscriber_id(),
                node_id=data.random_node_id(),
                event_sources=[
                    CategoryIdentifier(data.random_event_category_name())
                ],
            ),
        )

        removal = EventSubscriptionStateChange(
            type=EventSubscriptionStateChangeType.REMOVE,
            subscription=EventSubscriptionState(
                group=data.random_subscriber_group(),
                id=data.random_subscriber_id(),
                node_id=data.random_node_id(),
                event_sources=[
                    CategoryIdentifier(data.random_event_category_name())
                ],
            ),
        )

        with pytest.raises(ValueError):
            await store.apply(changes=[addition, removal])

        states = await store.list()

        assert states == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
