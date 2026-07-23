from __future__ import annotations

from dataclasses import dataclass

from .models import ConnectorCapabilities, ConnectorSpec
from .protocol import ConnectorFactory, DatabaseConnector


class ConnectorRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConnectorRegistration:
    engine: str
    factory: ConnectorFactory
    capabilities: ConnectorCapabilities


class ConnectorRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ConnectorRegistration] = {}

    def register(
        self,
        engine: str,
        factory: ConnectorFactory,
        capabilities: ConnectorCapabilities,
    ) -> None:
        normalized_engine = self._normalize_engine(engine)
        if normalized_engine in self._registrations:
            raise ConnectorRegistryError(
                "duplicate_connector",
                f"connector already registered for engine: {normalized_engine}",
            )
        self._registrations[normalized_engine] = ConnectorRegistration(
            engine=normalized_engine,
            factory=factory,
            capabilities=capabilities,
        )

    def get_registration(self, engine: str) -> ConnectorRegistration:
        normalized_engine = self._normalize_engine(engine)
        try:
            return self._registrations[normalized_engine]
        except KeyError as exc:
            raise ConnectorRegistryError(
                "engine_not_supported",
                f"database engine is not supported: {normalized_engine}",
            ) from exc

    def get_factory(self, engine: str) -> ConnectorFactory:
        return self.get_registration(engine).factory

    def capabilities(self, engine: str) -> ConnectorCapabilities:
        return self.get_registration(engine).capabilities

    def create(self, spec: ConnectorSpec) -> DatabaseConnector:
        registration = self.get_registration(spec.engine)
        connector = registration.factory(spec)
        connector_engine = self._normalize_engine(connector.engine)
        if connector_engine != registration.engine:
            try:
                connector.close()
            finally:
                raise ConnectorRegistryError(
                    "connector_engine_mismatch",
                    "connector factory returned an unexpected engine",
                )
        return connector

    def registered_engines(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    @staticmethod
    def _normalize_engine(engine: str) -> str:
        normalized_engine = engine.strip().lower()
        if not normalized_engine:
            raise ConnectorRegistryError("invalid_engine", "database engine must not be empty")
        return normalized_engine
