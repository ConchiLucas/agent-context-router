from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_prefix: str = "/api"
    database_url: str | None = None
    public_mcp_url: str = "http://127.0.0.1:49173/mcp"
    internal_mcp_url: str = "http://127.0.0.1:8000/mcp"
    mcp_test_timeout_seconds: float = 15.0
    database_tools_enabled: bool = True
    database_max_rows: int = 5_000
    database_max_result_bytes: int = 4_000_000
    database_max_query_timeout_ms: int = 30_000
    database_max_cached_connectors: int = 16
    database_max_concurrency_per_source: int = 4
    database_schema_result_bytes: int = 1_000_000
    workspace_host_root: Path = Path("/Users/conchi/workforce")
    workspace_container_root: Path = Path("/workspace")
    default_project_name: str | None = None
    default_agents_path: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="CONTEXT_ROUTER_",
        extra="ignore",
    )
