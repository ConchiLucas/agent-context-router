from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .models import ConnectorCacheKey, ConnectorSpec
from .protocol import DatabaseConnector
from .registry import ConnectorRegistry, ConnectorRegistryError


class ConnectorManagerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class _ConnectorEntry:
    key: ConnectorCacheKey
    connector: DatabaseConnector
    leases: int = 0
    retiring: bool = False
    closed: bool = False
    last_used: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class _InitializationFlight:
    source_generation: int
    done: threading.Event = field(default_factory=threading.Event)
    error: tuple[str, str] | None = None


class ConnectorManager:
    """Own lazy connector lifecycles without holding locks across database I/O."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        *,
        max_cached_connectors: int = 16,
        max_concurrency_per_source: int = 4,
    ) -> None:
        if min(max_cached_connectors, max_concurrency_per_source) < 1:
            raise ValueError("connector manager limits must be positive")
        self._registry = registry
        self._max_cached_connectors = max_cached_connectors
        self._max_concurrency_per_source = max_concurrency_per_source
        self._lock = threading.RLock()
        self._entries: dict[ConnectorCacheKey, _ConnectorEntry] = {}
        self._flights: dict[ConnectorCacheKey, _InitializationFlight] = {}
        self._source_limiters: dict[str, threading.BoundedSemaphore] = {}
        self._source_generations: dict[str, int] = {}
        self._latest_config_versions: dict[str, int] = {}
        self._latest_database_updates: dict[tuple[str, int, str], float] = {}
        self._active_leases = 0
        self._closed = False

    @contextmanager
    def lease(self, spec: ConnectorSpec) -> Iterator[DatabaseConnector]:
        limiter = self._source_limiter(spec.data_source_id)
        limiter.acquire()
        entry: _ConnectorEntry | None = None
        try:
            entry = self._acquire_entry(spec)
            yield entry.connector
        finally:
            if entry is not None:
                self._release_entry(entry)
            limiter.release()

    def invalidate_source(self, data_source_id: str) -> None:
        connectors_to_close: list[DatabaseConnector] = []
        with self._lock:
            self._source_generations[data_source_id] = (
                self._source_generations.get(data_source_id, 0) + 1
            )
            self._latest_config_versions.pop(data_source_id, None)
            self._latest_database_updates = {
                key: value
                for key, value in self._latest_database_updates.items()
                if key[0] != data_source_id
            }
            for key, entry in list(self._entries.items()):
                if key.data_source_id == data_source_id:
                    self._entries.pop(key, None)
                    connector = self._retire_entry_locked(entry)
                    if connector is not None:
                        connectors_to_close.append(connector)
            for key, flight in self._flights.items():
                if key.data_source_id == data_source_id and flight.error is None:
                    flight.error = (
                        "connection_failed",
                        "database connection configuration was invalidated",
                    )
                    flight.done.set()
        self._close_connectors(connectors_to_close)

    def close_all(self) -> None:
        connectors_to_close: list[DatabaseConnector] = []
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for key, entry in list(self._entries.items()):
                self._entries.pop(key, None)
                connector = self._retire_entry_locked(entry)
                if connector is not None:
                    connectors_to_close.append(connector)
            for flight in self._flights.values():
                if flight.error is None:
                    flight.error = ("connection_failed", "connector manager is closed")
                    flight.done.set()
        self._close_connectors(connectors_to_close)

    @property
    def cached_connector_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def active_lease_count(self) -> int:
        with self._lock:
            return self._active_leases

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _source_limiter(self, data_source_id: str) -> threading.BoundedSemaphore:
        with self._lock:
            if self._closed:
                raise ConnectorManagerError("connection_failed", "connector manager is closed")
            limiter = self._source_limiters.get(data_source_id)
            if limiter is None:
                limiter = threading.BoundedSemaphore(self._max_concurrency_per_source)
                self._source_limiters[data_source_id] = limiter
            return limiter

    def _acquire_entry(self, spec: ConnectorSpec) -> _ConnectorEntry:
        while True:
            creator = False
            with self._lock:
                self._ensure_open_locked()
                self._observe_spec_locked(spec)
                entry = self._entries.get(spec.cache_key)
                if entry is not None and not entry.retiring:
                    entry.leases += 1
                    entry.last_used = time.monotonic()
                    self._active_leases += 1
                    return entry

                flight = self._flights.get(spec.cache_key)
                if flight is None:
                    flight = _InitializationFlight(
                        source_generation=self._source_generations.get(spec.data_source_id, 0)
                    )
                    self._flights[spec.cache_key] = flight
                    creator = True

            if creator:
                return self._initialize_entry(spec, flight)

            flight.done.wait()
            if flight.error is not None:
                raise ConnectorManagerError(*flight.error)

    def _initialize_entry(
        self,
        spec: ConnectorSpec,
        flight: _InitializationFlight,
    ) -> _ConnectorEntry:
        connector: DatabaseConnector | None = None
        try:
            connector = self._registry.create(spec)
            connector.ping()
        except ConnectorRegistryError as exc:
            if connector is not None:
                self._close_connectors([connector])
            error = ConnectorManagerError(exc.code, str(exc))
            self._fail_flight(spec.cache_key, flight, error)
            raise error from None
        except Exception:
            if connector is not None:
                self._close_connectors([connector])
            error = ConnectorManagerError(
                "connection_failed",
                "database connector could not be initialized",
            )
            self._fail_flight(spec.cache_key, flight, error)
            raise error from None

        connectors_to_close: list[DatabaseConnector] = []
        publish_error: ConnectorManagerError | None = None
        with self._lock:
            if self._closed:
                publish_error = ConnectorManagerError(
                    "connection_failed",
                    "connector manager is closed",
                )
            elif flight.error is not None:
                publish_error = ConnectorManagerError(*flight.error)
            elif self._source_generations.get(spec.data_source_id, 0) != flight.source_generation:
                publish_error = ConnectorManagerError(
                    "connection_failed",
                    "database connection configuration was invalidated",
                )
            else:
                try:
                    self._observe_spec_locked(spec)
                except ConnectorManagerError as exc:
                    publish_error = exc

            if publish_error is None:
                for key, old_entry in list(self._entries.items()):
                    if key == spec.cache_key or key.data_source_id != spec.data_source_id:
                        continue
                    source_changed = key.config_version != spec.config_version
                    database_changed = key.database_id == spec.database_id
                    if source_changed or database_changed:
                        self._entries.pop(key, None)
                        old_connector = self._retire_entry_locked(old_entry)
                        if old_connector is not None:
                            connectors_to_close.append(old_connector)

                entry = _ConnectorEntry(
                    key=spec.cache_key,
                    connector=connector,
                    leases=1,
                )
                self._entries[spec.cache_key] = entry
                self._active_leases += 1
                connectors_to_close.extend(self._evict_lru_locked())
                self._complete_flight_locked(spec.cache_key, flight)
            else:
                self._complete_flight_locked(
                    spec.cache_key,
                    flight,
                    error=(publish_error.code, str(publish_error)),
                )

        if publish_error is not None:
            self._close_connectors([connector])
            raise publish_error
        self._close_connectors(connectors_to_close)
        return entry

    def _release_entry(self, entry: _ConnectorEntry) -> None:
        connectors_to_close: list[DatabaseConnector] = []
        with self._lock:
            if entry.leases < 1:
                return
            entry.leases -= 1
            self._active_leases -= 1
            entry.last_used = time.monotonic()
            if entry.retiring or self._closed:
                connector = self._retire_entry_locked(entry)
                if connector is not None:
                    connectors_to_close.append(connector)
            else:
                connectors_to_close.extend(self._evict_lru_locked())
        self._close_connectors(connectors_to_close)

    def _observe_spec_locked(self, spec: ConnectorSpec) -> None:
        latest_version = self._latest_config_versions.get(spec.data_source_id)
        if latest_version is not None and spec.config_version < latest_version:
            raise ConnectorManagerError(
                "connection_failed",
                "database connection configuration is stale",
            )
        if latest_version is None or spec.config_version > latest_version:
            self._latest_config_versions[spec.data_source_id] = spec.config_version

        update_key = (spec.data_source_id, spec.config_version, spec.database_id)
        update_value = self._datetime_order_value(spec.database_updated_at)
        latest_update = self._latest_database_updates.get(update_key)
        if latest_update is not None and update_value < latest_update:
            raise ConnectorManagerError(
                "connection_failed",
                "database connection target is stale",
            )
        if latest_update is None or update_value > latest_update:
            self._latest_database_updates[update_key] = update_value

    def _evict_lru_locked(self) -> list[DatabaseConnector]:
        connectors: list[DatabaseConnector] = []
        while len(self._entries) > self._max_cached_connectors:
            candidates = [entry for entry in self._entries.values() if entry.leases == 0]
            if not candidates:
                break
            oldest = min(candidates, key=lambda entry: entry.last_used)
            if self._entries.get(oldest.key) is oldest:
                self._entries.pop(oldest.key, None)
            connector = self._retire_entry_locked(oldest)
            if connector is not None:
                connectors.append(connector)
        return connectors

    @staticmethod
    def _retire_entry_locked(entry: _ConnectorEntry) -> DatabaseConnector | None:
        entry.retiring = True
        if entry.leases == 0 and not entry.closed:
            entry.closed = True
            return entry.connector
        return None

    def _fail_flight(
        self,
        key: ConnectorCacheKey,
        flight: _InitializationFlight,
        error: ConnectorManagerError,
    ) -> None:
        with self._lock:
            self._complete_flight_locked(key, flight, error=(error.code, str(error)))

    def _complete_flight_locked(
        self,
        key: ConnectorCacheKey,
        flight: _InitializationFlight,
        *,
        error: tuple[str, str] | None = None,
    ) -> None:
        if error is not None and flight.error is None:
            flight.error = error
        if self._flights.get(key) is flight:
            self._flights.pop(key, None)
        flight.done.set()

    def _ensure_open_locked(self) -> None:
        if self._closed:
            raise ConnectorManagerError("connection_failed", "connector manager is closed")

    @staticmethod
    def _datetime_order_value(value: datetime) -> float:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.timestamp()

    @staticmethod
    def _close_connectors(connectors: list[DatabaseConnector]) -> None:
        for connector in connectors:
            try:
                connector.close()
            except Exception:
                # Closing is best-effort and must never replace the query result or
                # expose a driver exception containing connection credentials.
                continue
