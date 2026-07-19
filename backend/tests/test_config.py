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


def test_settings_reads_documents_roots(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT", "/srv/ai-docs")
    monkeypatch.setenv("CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT", "/documents")

    settings = Settings(_env_file=None)

    assert settings.documents_host_root == "/srv/ai-docs"
    assert settings.documents_container_root == "/documents"
