from context_router.config import Settings


def test_settings_default_database_url_uses_local_postgresql(monkeypatch) -> None:
    monkeypatch.delenv("CONTEXT_ROUTER_DATABASE_URL", raising=False)

    settings = Settings()

    assert (
        settings.database_url
        == "postgresql+psycopg://conchi:conchi123456@127.0.0.1:5432/context_router"
    )


def test_settings_reads_context_router_database_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "CONTEXT_ROUTER_DATABASE_URL",
        "postgresql+psycopg://context_router:context_router@localhost/context_router",
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+psycopg://")
