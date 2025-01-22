from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from psycopg import AsyncConnection, AsyncCursor, sql
from psycopg.rows import TupleRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from logicblocks.event.db.postgres import (
    Column,
    Condition,
    ConnectionSettings,
    ConnectionSource,
    ParameterisedQuery,
    SortDirection,
    Value,
)
from logicblocks.event.db.postgres import (
    Operator as DBOperator,
)
from logicblocks.event.db.postgres import (
    Query as DBQuery,
)
from logicblocks.event.types import Projection, identifier

from ..query import (
    Clause,
    FilterClause,
    KeySetPagingClause,
    Lookup,
    OffsetPagingClause,
    Operator,
    Path,
    Query,
    Search,
    SortClause,
    SortOrder,
)
from .base import ProjectionStorageAdapter


@dataclass(frozen=True)
class PostgresTableSettings:
    projections_table_name: str

    def __init__(self, *, projections_table_name: str = "projections"):
        object.__setattr__(
            self, "projections_table_name", projections_table_name
        )


type PostgresClauseApplicator[C: Clause] = Callable[
    [C, DBQuery, PostgresTableSettings], DBQuery
]


def sort_direction_for_query_sort_order(
    order: SortOrder,
) -> SortDirection:
    match order:
        case SortOrder.ASC:
            return SortDirection.ASC
        case SortOrder.DESC:
            return SortDirection.DESC
        case _:  # pragma: no cover
            raise ValueError(f"Unsupported sort order: {order}")


def column_for_query_path(
    path: Path,
) -> Column:
    if path.is_nested():
        return Column(field=path.top_level, path=path.sub_levels)
    else:
        return Column(field=path.top_level)


def path_expression_for_query_path(path: Path) -> str:
    path_list = ",".join([str(sub_level) for sub_level in path.sub_levels])
    return "{" + path_list + "}"


operator_for_query_operator_map = {
    Operator.EQUAL: DBOperator.EQUALS,
    Operator.NOT_EQUAL: DBOperator.NOT_EQUALS,
    Operator.LESS_THAN: DBOperator.LESS_THAN,
    Operator.LESS_THAN_OR_EQUAL: DBOperator.LESS_THAN_OR_EQUAL,
    Operator.GREATER_THAN: DBOperator.GREATER_THAN,
    Operator.GREATER_THAN_OR_EQUAL: DBOperator.GREATER_THAN_OR_EQUAL,
}


def operator_for_query_operator(operator: Operator) -> DBOperator:
    if operator not in operator_for_query_operator_map:
        raise ValueError(f"Unsupported operator: {operator}")

    return operator_for_query_operator_map[operator]


def filter_clause_applicator(
    filter: FilterClause, query: DBQuery, table_settings: PostgresTableSettings
) -> DBQuery:
    return query.where(
        Condition()
        .left(Column(field=filter.path.top_level, path=filter.path.sub_levels))
        .operator(operator_for_query_operator(filter.operator))
        .right(
            Value(
                filter.value,
                wrapper="to_jsonb" if filter.path.is_nested() else None,
            )
        )
    )


def sort_clause_applicator(
    sort: SortClause, query: DBQuery, table_settings: PostgresTableSettings
) -> DBQuery:
    order_by_fields: list[tuple[Column, SortDirection]] = []
    for field in sort.fields:
        order_by_fields.append(
            (
                column_for_query_path(field.path),
                sort_direction_for_query_sort_order(field.order),
            )
        )

    return query.order_by(*order_by_fields)


def key_set_paging_clause_applicator(
    paging: KeySetPagingClause,
    query: DBQuery,
    table_settings: PostgresTableSettings,
) -> DBQuery:
    id_column = Column(field="id")

    has_after_id = paging.after_id is not None
    has_before_id = paging.before_id is not None

    after_id = Value(paging.after_id) if has_after_id else None
    before_id = Value(paging.before_id) if has_before_id else None

    existing_sort = [
        (sort_column.expression, sort_column.direction)
        for sort_column in query.sort_columns
    ]
    has_existing_sort = len(existing_sort) > 0

    # all_sort_asc = all(
    #     direction == SortDirection.ASC for _, direction in existing_sort
    # )
    # all_sort_desc = all(
    #     direction == SortDirection.DESC for _, direction in existing_sort
    # )

    paged_sort = list(existing_sort) + [(id_column, SortDirection.ASC)]
    paged_sort_columns = [column for column, _ in paged_sort]

    def row_comparison_condition(
        columns: Iterable[Column], operator: DBOperator, table: str
    ) -> Condition:
        right = DBQuery().select_all().from_table(table)
        return Condition().left(columns).operator(operator).right(right)

    def field_comparison_condition(
        column: Column, operator: DBOperator, value: Value
    ) -> Condition:
        return Condition().left(column).operator(operator).right(value)

    def record_query(id: Value, columns: Iterable[Column]) -> DBQuery:
        return (
            DBQuery()
            .select(*columns)
            .from_table(table_settings.projections_table_name)
            .where(
                field_comparison_condition(id_column, DBOperator.EQUALS, id)
            )
            .limit(1)
        )

    # factors are:
    #  - whether paging forwards or backwards
    #      - if after id, paging forwards, treat before id as constraint
    #      - if only before id, paging backwards
    #      - if neither, first page
    #  - whether there is an existing sort
    #      - all ASC -> paging forwards, no wrap, paging backwards, wrap
    #      - all DESC -> paging forwards, wrap, paging backwards, no wrap
    #      - mixed -> union, not sure how to change forwards/backwards

    if has_existing_sort:
        if after_id is not None:
            return (
                query.clone(sort_columns=[])
                .with_query(
                    record_query(after_id, paged_sort_columns), name="after"
                )
                .where(
                    row_comparison_condition(
                        paged_sort_columns,
                        DBOperator.GREATER_THAN,
                        table="after",
                    )
                )
                .order_by(*paged_sort)
                .limit(paging.item_count)
            )
        else:
            return (
                query.clone(sort_columns=[])
                .order_by(*paged_sort)
                .limit(paging.item_count)
            )
    else:
        if after_id is not None:
            query = (
                query.clone(sort_columns=[])
                .where(
                    field_comparison_condition(
                        id_column, DBOperator.GREATER_THAN, after_id
                    )
                )
                .order_by(*paged_sort)
                .limit(paging.item_count)
            )

            if before_id is not None:
                query = query.where(
                    field_comparison_condition(
                        id_column, DBOperator.LESS_THAN, before_id
                    )
                )

            return query
        elif before_id is not None:
            return (
                DBQuery()
                .select_all()
                .from_subquery(
                    (
                        query.where(
                            field_comparison_condition(
                                id_column, DBOperator.LESS_THAN, before_id
                            )
                        )
                        .order_by(("id", SortDirection.DESC))
                        .limit(paging.item_count)
                    ),
                    alias="page",
                )
                .order_by("id")
                .limit(paging.item_count)
            )
        else:
            return query.order_by("id").limit(paging.item_count)


def offset_paging_clause_applicator(
    paging: OffsetPagingClause,
    query: DBQuery,
    table_settings: PostgresTableSettings,
) -> DBQuery:
    if paging.page_number == 1:
        return query.limit(paging.item_count)
    else:
        return query.limit(paging.item_count).offset(paging.offset)


class PostgresQueryConverter:
    def __init__(
        self, table_settings: PostgresTableSettings = PostgresTableSettings()
    ):
        self._registry: dict[type[Clause], PostgresClauseApplicator[Any]] = {}
        self._table_settings = table_settings

    def with_default_clause_applicators(self) -> Self:
        return (
            self.register_clause_applicator(
                FilterClause, filter_clause_applicator
            )
            .register_clause_applicator(SortClause, sort_clause_applicator)
            .register_clause_applicator(
                KeySetPagingClause, key_set_paging_clause_applicator
            )
            .register_clause_applicator(
                OffsetPagingClause, offset_paging_clause_applicator
            )
        )

    def register_clause_applicator[C: Clause](
        self, clause_type: type[C], applicator: PostgresClauseApplicator[C]
    ) -> Self:
        self._registry[clause_type] = applicator
        return self

    def apply_clause(self, clause: Clause, query_builder: DBQuery) -> DBQuery:
        applicator = self._registry.get(type(clause))
        if applicator is None:
            raise ValueError(f"No converter registered for {type(clause)}")
        return applicator(clause, query_builder, self._table_settings)

    def convert_query(self, query: Query) -> ParameterisedQuery:
        builder = (
            DBQuery()
            .select_all()
            .from_table(self._table_settings.projections_table_name)
        )

        match query:
            case Lookup(filters):
                for filter in filters:
                    builder = self.apply_clause(filter, builder)
                return builder.build()
            case Search(filters, sort, paging):
                for filter in filters:
                    builder = self.apply_clause(filter, builder)
                if sort is not None:
                    builder = self.apply_clause(sort, builder)
                if paging is not None:
                    builder = self.apply_clause(paging, builder)
                return builder.build()
            case _:
                raise ValueError(f"Unsupported query: {query}")


def insert_query(
    projection: Projection[Mapping[str, Any]],
    table_settings: PostgresTableSettings,
) -> ParameterisedQuery:
    return (
        sql.SQL(
            """
            INSERT INTO {0} (
              id, 
              name, 
              state, 
              source,
              version
            )
              VALUES (%s, %s, %s, %s, %s)
              ON CONFLICT (id) 
              DO UPDATE
            SET (state, version) = (%s, %s);
            """
        ).format(sql.Identifier(table_settings.projections_table_name)),
        [
            projection.id,
            projection.name,
            Jsonb(projection.state),
            Jsonb(projection.source.dict()),
            projection.version,
            Jsonb(projection.state),
            projection.version,
        ],
    )


async def upsert(
    cursor: AsyncCursor[TupleRow],
    *,
    projection: Projection[Mapping[str, Any]],
    table_settings: PostgresTableSettings,
):
    await cursor.execute(*insert_query(projection, table_settings))


def lift_projection[S, T](
    projection: Projection[S],
    converter: Callable[[S], T],
) -> Projection[T]:
    return Projection[T](
        id=projection.id,
        name=projection.name,
        state=converter(projection.state),
        version=projection.version,
        source=projection.source,
    )


class PostgresProjectionStorageAdapter[OQ: Query = Lookup, MQ: Query = Search](
    ProjectionStorageAdapter[OQ, MQ]
):
    def __init__(
        self,
        *,
        connection_source: ConnectionSource,
        table_settings: PostgresTableSettings = PostgresTableSettings(),
        query_converter: PostgresQueryConverter | None = None,
    ):
        if isinstance(connection_source, ConnectionSettings):
            self._connection_pool_owner = True
            self.connection_pool = AsyncConnectionPool[AsyncConnection](
                connection_source.to_connection_string(), open=False
            )
        else:
            self._connection_pool_owner = False
            self.connection_pool = connection_source

        self.table_settings = table_settings
        self.query_converter = (
            query_converter
            if query_converter is not None
            else (PostgresQueryConverter().with_default_clause_applicators())
        )

    async def open(self) -> None:
        if self._connection_pool_owner:
            await self.connection_pool.open()

    async def close(self) -> None:
        if self._connection_pool_owner:
            await self.connection_pool.close()

    async def save[T](
        self,
        *,
        projection: Projection[T],
        converter: Callable[[T], Mapping[str, Any]],
    ) -> None:
        async with self.connection_pool.connection() as connection:
            async with connection.cursor() as cursor:
                await upsert(
                    cursor,
                    projection=lift_projection(projection, converter),
                    table_settings=self.table_settings,
                )

    async def find_one[T](
        self, *, lookup: OQ, converter: Callable[[Mapping[str, Any]], T]
    ) -> Projection[T] | None:
        query = self.query_converter.convert_query(lookup)
        async with self.connection_pool.connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                results = await cursor.execute(*query)
                if results.rowcount > 1:
                    raise ValueError(
                        f"Expected single projection for query: {lookup} "
                        f"but found {results.rowcount} projections: "
                        f"{await results.fetchmany()}."
                    )

                projection_dict = await results.fetchone()
                if projection_dict is None:
                    return None

                projection = Projection[Mapping[str, Any]](
                    id=projection_dict["id"],
                    name=projection_dict["name"],
                    state=projection_dict["state"],
                    version=projection_dict["version"],
                    source=identifier.event_sequence_identifier(
                        projection_dict["source"]
                    ),
                )

                return lift_projection(projection, converter)

    async def find_many[T](
        self, *, search: MQ, converter: Callable[[Mapping[str, Any]], T]
    ) -> Sequence[Projection[T]]:
        raise NotImplementedError()
