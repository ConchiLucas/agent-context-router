from context_router.config import Settings


def test_settings_reads_context_router_database_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "CONTEXT_ROUTER_DATABASE_URL",
        "postgresql+psycopg://context_router:context_router@localhost/context_router",
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+psycopg://")
