import pytest

import threading
import concurrent.futures

from abc import ABC, abstractmethod
from collections.abc import Sequence, Set
from itertools import batched

from logicblocks.event.store import conditions as writeconditions
from logicblocks.event.store.adapters import StorageAdapter
from logicblocks.event.store.exceptions import UnmetWriteConditionError
from logicblocks.event.testing import NewEventBuilder
from logicblocks.event.testing.data import (
    random_event_category_name,
    random_event_stream_name,
)
from logicblocks.event.types import StoredEvent, identifier, NewEvent


class ConcurrencyParameters(object):
    def __init__(self, *, concurrent_writes: int, repeats: int):
        self.concurrent_writes = concurrent_writes
        self.repeats = repeats


class Base(ABC):
    @abstractmethod
    def clear_storage(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    def construct_storage_adapter(self) -> StorageAdapter:
        raise NotImplementedError()

    @abstractmethod
    def retrieve_events(
        self,
        *,
        adapter: StorageAdapter,
        category: str | None = None,
        stream: str | None = None,
    ) -> Sequence[StoredEvent]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def concurrency_parameters(self) -> ConcurrencyParameters:
        raise NotImplementedError()


class SaveCases(Base, ABC):
    def test_stores_single_event_for_later_retrieval(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event = NewEventBuilder().build()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event],
        )
        stored_event = stored_events[0]

        actual_events = self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event.id,
                name=new_event.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event.payload,
                observed_at=new_event.observed_at,
                occurred_at=new_event.occurred_at,
            )
        ]

        assert actual_events == expected_events

    def test_stores_multiple_events_in_same_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1, new_event_2],
        )
        stored_event_1 = stored_events[0]
        stored_event_2 = stored_events[1]

        actual_events = self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_events == expected_events

    def test_stores_multiple_events_in_sequential_saves(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1],
        )
        stored_event_1 = stored_events_1[0]

        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event_2],
        )
        stored_event_2 = stored_events_2[0]

        actual_events = self.retrieve_events(adapter=adapter)
        expected_events = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_events == expected_events


class WriteConditionCases(Base, ABC):
    def test_writes_if_empty_stream_condition_and_stream_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event = NewEventBuilder().build()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event],
            conditions={writeconditions.stream_is_empty()},
        )
        stored_event = stored_events[0]

        actual_events = self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream
        )
        expected_events = [
            StoredEvent(
                id=stored_event.id,
                name=new_event.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event.payload,
                observed_at=new_event.observed_at,
                occurred_at=new_event.occurred_at,
            )
        ]

        assert actual_events == expected_events

    def test_writes_if_empty_stream_condition_and_category_not_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[new_event_1],
        )

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[new_event_2],
            conditions={writeconditions.stream_is_empty()},
        )
        stored_event = stored_events[0]

        actual_records = self.retrieve_events(
            adapter=adapter, category=event_category, stream=event_stream_2
        )
        expected_records = [
            StoredEvent(
                id=stored_event.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream_2,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            )
        ]

        assert actual_records == expected_records

    def test_writes_if_empty_stream_condition_and_log_not_empty(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream_1
            ),
            events=[new_event_1],
        )

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream_2
            ),
            events=[new_event_2],
            conditions={writeconditions.stream_is_empty()},
        )
        stored_event = stored_events[0]

        actual_records = self.retrieve_events(
            adapter=adapter, category=event_category_2, stream=event_stream_2
        )
        expected_records = [
            StoredEvent(
                id=stored_event.id,
                name=new_event_2.name,
                category=event_category_2,
                stream=event_stream_2,
                position=0,
                sequence_number=stored_event.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            )
        ]

        assert actual_records == expected_records

    def test_raises_if_empty_stream_condition_and_stream_not_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        with pytest.raises(UnmetWriteConditionError):
            adapter.save(
                target=identifier.Stream(
                    category=event_category, stream=event_stream
                ),
                events=[NewEventBuilder().build()],
                conditions={writeconditions.stream_is_empty()},
            )

    def test_writes_if_position_condition_and_correct_position(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        new_event_1 = NewEventBuilder().build()
        new_event_2 = NewEventBuilder().build()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event_1],
        )
        stored_event_1 = stored_events_1[0]

        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[new_event_2],
            conditions={writeconditions.position_is(0)},
        )

        stored_event_2 = stored_events_2[0]

        actual_records = self.retrieve_events(adapter=adapter)
        expected_records = [
            StoredEvent(
                id=stored_event_1.id,
                name=new_event_1.name,
                category=event_category,
                stream=event_stream,
                position=0,
                sequence_number=stored_event_1.sequence_number,
                payload=new_event_1.payload,
                observed_at=new_event_1.observed_at,
                occurred_at=new_event_1.occurred_at,
            ),
            StoredEvent(
                id=stored_event_2.id,
                name=new_event_2.name,
                category=event_category,
                stream=event_stream,
                position=1,
                sequence_number=stored_event_2.sequence_number,
                payload=new_event_2.payload,
                observed_at=new_event_2.observed_at,
                occurred_at=new_event_2.occurred_at,
            ),
        ]

        assert actual_records == expected_records

    def test_raises_if_position_condition_and_less_than_expected(self):
        adapter = self.construct_storage_adapter()

        adapter.save(
            target=identifier.Stream(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        with pytest.raises(UnmetWriteConditionError):
            adapter.save(
                target=identifier.Stream(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                conditions={writeconditions.position_is(1)},
            )

    def test_raises_if_position_condition_and_greater_than_expected(self):
        adapter = self.construct_storage_adapter()

        adapter.save(
            target=identifier.Stream(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        with pytest.raises(UnmetWriteConditionError):
            adapter.save(
                target=identifier.Stream(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                conditions={writeconditions.position_is(1)},
            )

    def test_raises_if_position_condition_and_stream_empty(self):
        adapter = self.construct_storage_adapter()

        with pytest.raises(UnmetWriteConditionError):
            adapter.save(
                target=identifier.Stream(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                ),
                events=[NewEventBuilder().build()],
                conditions={writeconditions.position_is(0)},
            )


class StorageAdapterSaveTask(object):
    adapter: StorageAdapter
    target: identifier.Stream
    events: Sequence[NewEvent]
    conditions: Set[writeconditions.WriteCondition]
    result: Sequence[StoredEvent] | None = None
    exception: BaseException | None = None

    def __init__(
        self,
        *,
        adapter: StorageAdapter,
        target: identifier.Stream,
        events: Sequence[NewEvent],
        conditions: Set[writeconditions.WriteCondition] | None = None,
    ):
        self.adapter = adapter
        self.target = target
        self.events = events
        self.conditions = frozenset() if conditions is None else conditions

    def execute(
        self,
    ) -> None:
        try:
            self.result = self.adapter.save(
                target=self.target,
                events=self.events,
                conditions=self.conditions,
            )
        except BaseException as e:
            self.exception = e


# TODO: Work out how to make these tests reliable on all machines.
#       Since they test race conditions they aren't perfectly repeatable,
#       although the chosen concurrency and number of repeats means they are
#       _relatively_ reliable on at least Toby's machine.
#
#       Potentially through a combination of hooks and barriers, these could
#       be made more reliable still but it would potentially leak implementation
#       details.
class ConcurrencyCases(Base, ABC):
    def test_simultaneous_checked_writes_to_empty_stream_write_once(self):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for test_repeat in range(test_repeats):
            self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            target = identifier.Stream(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter,
                    target=target,
                    events=[
                        (
                            NewEventBuilder()
                            .with_name(f"event-1-for-thread-${thread_id}")
                            .build()
                        ),
                        (
                            NewEventBuilder()
                            .with_name(f"event-2-for-thread-${thread_id}")
                            .build()
                        ),
                    ],
                    conditions={writeconditions.stream_is_empty()},
                )
                for thread_id in range(test_concurrency)
            ]

            threads = [threading.Thread(target=task.execute) for task in tasks]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            failed_saves = [
                task.exception for task in tasks if task.exception is not None
            ]
            successful_saves = [
                task.result for task in tasks if task.result is not None
            ]

            is_single_successful_save = len(successful_saves) == 1
            is_all_others_failed_saves = (
                len(failed_saves) == test_concurrency - 1
            )
            is_correct_save_counts = (
                is_single_successful_save and is_all_others_failed_saves
            )

            actual_records = self.retrieve_events(
                adapter=adapter, category=event_category, stream=event_stream
            )
            expected_records = None

            is_expected_events = False
            if is_correct_save_counts:
                expected_records = successful_saves[0]
                is_expected_events = actual_records == expected_records

            test_results.append(
                {
                    "passed": is_correct_save_counts and is_expected_events,
                    "successful_saves": len(successful_saves),
                    "failed_saves": len(failed_saves),
                    "actual_records": actual_records,
                    "expected_records": expected_records,
                }
            )

        failing_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert len(failing_tests) == 0, (
            f"{len(failing_tests)} out of {test_repeats} failed: "
            f"{failing_tests}"
        )

    def test_simultaneous_checked_writes_to_existing_stream_write_once(self):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for test_repeat in range(test_repeats):
            self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            preexisting_events = adapter.save(
                target=identifier.Stream(
                    category=event_category, stream=event_stream
                ),
                events=[
                    (
                        NewEventBuilder()
                        .with_name("event-1-preexisting")
                        .build()
                    ),
                    (
                        NewEventBuilder()
                        .with_name("event-2-preexisting")
                        .build()
                    ),
                ],
            )

            target = identifier.Stream(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter,
                    target=target,
                    events=[
                        (
                            NewEventBuilder()
                            .with_name(f"event-1-for-thread-${thread_id}")
                            .build()
                        ),
                        (
                            NewEventBuilder()
                            .with_name(f"event-2-for-thread-${thread_id}")
                            .build()
                        ),
                    ],
                    conditions={writeconditions.position_is(1)},
                )
                for thread_id in range(test_concurrency)
            ]

            threads = [threading.Thread(target=task.execute) for task in tasks]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            failed_saves = [
                task.exception for task in tasks if task.exception is not None
            ]
            successful_saves = [
                task.result for task in tasks if task.result is not None
            ]

            is_single_successful_save = len(successful_saves) == 1
            is_all_others_failed_saves = (
                len(failed_saves) == test_concurrency - 1
            )
            is_correct_save_counts = (
                is_single_successful_save and is_all_others_failed_saves
            )

            actual_records = self.retrieve_events(
                adapter=adapter, category=event_category, stream=event_stream
            )
            expected_records = None

            is_expected_events = False
            if is_correct_save_counts:
                expected_records = list(preexisting_events) + list(
                    successful_saves[0]
                )
                is_expected_events = actual_records == expected_records

            test_results.append(
                {
                    "passed": is_correct_save_counts and is_expected_events,
                    "successful_saves": len(successful_saves),
                    "failed_saves": len(failed_saves),
                    "actual_records": actual_records,
                    "expected_records": expected_records,
                }
            )

        failing_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert len(failing_tests) == 0, (
            f"{len(failing_tests)} out of {test_repeats} failed: "
            f"{failing_tests}"
        )

    def test_simultaneous_unchecked_writes_are_serialised(self):
        test_concurrency = self.concurrency_parameters.concurrent_writes
        test_repeats = self.concurrency_parameters.repeats

        test_results = []

        for test_repeat in range(test_repeats):
            self.clear_storage()

            adapter = self.construct_storage_adapter()

            event_category = random_event_category_name()
            event_stream = random_event_stream_name()

            event_writes = [
                [
                    NewEventBuilder()
                    .with_name(f"event-1-write-{write_id}")
                    .build(),
                    NewEventBuilder()
                    .with_name(f"event-2-write-{write_id}")
                    .build(),
                    NewEventBuilder()
                    .with_name(f"event-3-write-{write_id}")
                    .build(),
                ]
                for write_id in range(test_concurrency)
            ]

            target = identifier.Stream(
                category=event_category, stream=event_stream
            )

            tasks = [
                StorageAdapterSaveTask(
                    adapter=adapter, target=target, events=events
                )
                for events in event_writes
            ]

            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(lambda task: task.execute(), tasks)

            actual_events = self.retrieve_events(
                adapter=adapter,
                category=event_category,
                stream=event_stream,
            )
            actual_names = [event.name for event in actual_events]
            actual_name_groups = set(batched(actual_names, 3))
            expected_name_groups = {
                tuple(event.name for event in event_write)
                for event_write in event_writes
            }

            actual_positions = [event.position for event in actual_events]
            expected_positions = list(range(test_concurrency * 3))

            is_correct_event_count = len(actual_events) == test_concurrency * 3
            is_correct_event_sequencing = (
                actual_name_groups == expected_name_groups
            )
            is_correct_event_positioning = (
                actual_positions == expected_positions
            )

            test_results.append(
                {
                    "passed": (
                        is_correct_event_count
                        and is_correct_event_sequencing
                        and is_correct_event_positioning
                    ),
                    "actual_name_groups": actual_name_groups,
                    "expected_name_groups": expected_name_groups,
                    "actual_positions": actual_positions,
                    "expected_positions": expected_positions,
                }
            )

        failed_tests = [
            test_result
            for test_result in test_results
            if not test_result["passed"]
        ]

        assert (
            len(failed_tests) == 0
        ), f"{len(failed_tests)} out of {test_repeats} failed: {failed_tests}"


class ScanCases(Base, ABC):
    def test_log_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = list(adapter.scan(target=identifier.Log()))

        assert scanned_events == []

    def test_log_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = list(adapter.scan(target=identifier.Log()))

        assert scanned_events == stored_events

    def test_log_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=random_event_category_name(),
                stream=random_event_stream_name(),
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = list(adapter.scan(target=identifier.Log()))

        assert scanned_events == stored_events

    def test_log_scan_scans_events_across_streams_in_sequence_order(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = list(adapter.scan(target=identifier.Log()))

        assert scanned_events == stored_events

    def test_log_scan_scans_events_across_categories_in_sequence_order(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = list(adapter.scan(target=identifier.Log()))

        assert scanned_events == stored_events

    def test_category_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = list(
            adapter.scan(
                target=identifier.Category(
                    category=random_event_category_name()
                )
            )
        )

        assert scanned_events == []

    def test_category_scan_scans_no_events_when_category_empty(self):
        adapter = self.construct_storage_adapter()

        scan_event_category = random_event_category_name()
        other_event_category = random_event_category_name()

        adapter.save(
            target=identifier.Stream(
                category=other_event_category,
                stream=random_event_stream_name(),
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = list(
            adapter.scan(
                target=identifier.Category(category=scan_event_category)
            )
        )

        assert scanned_events == []

    def test_category_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = list(
            adapter.scan(target=identifier.Category(category=event_category))
        )

        assert scanned_events == stored_events

    def test_category_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category,
                stream=event_stream,
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = list(
            adapter.scan(target=identifier.Category(category=event_category))
        )

        assert scanned_events == stored_events

    def test_category_scan_scans_events_across_streams_in_sequence_order(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = list(
            adapter.scan(target=identifier.Category(category=event_category))
        )

        assert scanned_events == stored_events

    def test_category_scan_ignores_events_in_other_categories(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = list(
            adapter.scan(target=identifier.Category(category=event_category_1))
        )

        assert scanned_events == stored_events

    def test_stream_scan_scans_no_events_when_store_empty(self):
        adapter = self.construct_storage_adapter()

        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=random_event_category_name(),
                    stream=random_event_stream_name(),
                )
            )
        )

        assert scanned_events == []

    def test_stream_scan_scans_no_events_when_stream_empty(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        scan_event_stream = random_event_stream_name()
        other_event_stream = random_event_stream_name()

        adapter.save(
            target=identifier.Stream(
                category=event_category, stream=other_event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category,
                    stream=scan_event_stream,
                )
            )
        )

        assert scanned_events == []

    def test_stream_scan_scans_single_event_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category, stream=event_stream
                )
            )
        )

        assert scanned_events == stored_events

    def test_stream_scan_scans_multiple_events_in_single_stream(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )

        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category, stream=event_stream
                )
            )
        )

        assert scanned_events == stored_events

    def test_stream_scan_scans_events_within_stream_in_sequence_order(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_2 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_4 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = (
            list(stored_events_1)
            + list(stored_events_2)
            + list(stored_events_3)
            + list(stored_events_4)
        )
        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category, stream=event_stream
                )
            )
        )

        assert scanned_events == stored_events

    def test_stream_scan_ignores_events_in_other_streams(self):
        adapter = self.construct_storage_adapter()

        event_category = random_event_category_name()
        event_stream_1 = random_event_stream_name()
        event_stream_2 = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_1
            ),
            events=[NewEventBuilder().build()],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category, stream=event_stream_2
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category, stream=event_stream_1
                )
            )
        )

        assert scanned_events == stored_events

    def test_stream_scan_ignores_events_in_other_categories(self):
        adapter = self.construct_storage_adapter()

        event_category_1 = random_event_category_name()
        event_category_2 = random_event_category_name()
        event_stream = random_event_stream_name()

        stored_events_1 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream
            ),
            events=[
                NewEventBuilder().build(),
                NewEventBuilder().build(),
            ],
        )
        stored_events_3 = adapter.save(
            target=identifier.Stream(
                category=event_category_1, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )
        adapter.save(
            target=identifier.Stream(
                category=event_category_2, stream=event_stream
            ),
            events=[NewEventBuilder().build()],
        )

        stored_events = list(stored_events_1) + list(stored_events_3)
        scanned_events = list(
            adapter.scan(
                target=identifier.Stream(
                    category=event_category_1, stream=event_stream
                )
            )
        )

        assert scanned_events == stored_events


class StorageAdapterCases(
    SaveCases, WriteConditionCases, ConcurrencyCases, ScanCases, ABC
):
    pass
