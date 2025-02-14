from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Self

from logicblocks.event.store import EventSource
from logicblocks.event.store.adapters import (
    InMemoryEventStorageAdapter,
    PostgresEventStorageAdapter,
)
from logicblocks.event.store.adapters.base import EventStorageAdapter
from logicblocks.event.store.store import EventCategory, EventStream
from logicblocks.event.types import (
    CategoryIdentifier,
    EventSourceIdentifier,
    StreamIdentifier,
)

from .base import EventSourceFactory


def construct_event_category(
    identifier: CategoryIdentifier, adapter: EventStorageAdapter
) -> EventCategory:
    return EventCategory(adapter, identifier)


def construct_event_stream(
    identifier: StreamIdentifier, adapter: EventStorageAdapter
) -> EventStream:
    return EventStream(adapter, identifier)


type AdaptorConstructor[I: EventSourceIdentifier] = Callable[
    [I, EventStorageAdapter], EventSource[I]
]


class EventStoreEventSourceConstructors:
    def __init__(self):
        self._d: dict[
            type[EventSourceIdentifier],
            AdaptorConstructor[Any],
        ] = {}

    def set_constructor[I: EventSourceIdentifier](
        self,
        identifier: type[I],
        constructor: AdaptorConstructor[I],
    ) -> Self:
        self._d[identifier] = constructor
        return self

    def get_constructor[I: EventSourceIdentifier](
        self, identifier: type[I]
    ) -> AdaptorConstructor[I]:
        return self._d[identifier]


class EventStoreEventSourceFactory(
    EventSourceFactory[EventStorageAdapter], ABC
):
    def __init__(self):
        self._constructors = EventStoreEventSourceConstructors()

        (
            self.register_constructor(
                CategoryIdentifier, construct_event_category
            ).register_constructor(StreamIdentifier, construct_event_stream)
        )

    @property
    @abstractmethod
    def storage_adapter(self) -> EventStorageAdapter:
        raise NotImplementedError()

    def register_constructor[I: EventSourceIdentifier](
        self,
        identifier_type: type[I],
        constructor: AdaptorConstructor[I],
    ) -> Self:
        self._constructors.set_constructor(identifier_type, constructor)
        return self

    def construct[I: EventSourceIdentifier](
        self, identifier: I
    ) -> EventSource[I]:
        return self._constructors.get_constructor(type(identifier))(
            identifier, self.storage_adapter
        )


class InMemoryEventStoreEventSourceFactory(EventStoreEventSourceFactory):
    def __init__(self, adapter: InMemoryEventStorageAdapter):
        super().__init__()
        self._adapter = adapter

    @property
    def storage_adapter(self) -> EventStorageAdapter:
        return self._adapter


class PostgresEventStoreEventSourceFactory(EventStoreEventSourceFactory):
    def __init__(self, adapter: PostgresEventStorageAdapter):
        super().__init__()
        self._adapter = adapter

    @property
    def storage_adapter(self) -> EventStorageAdapter:
        return self._adapter
