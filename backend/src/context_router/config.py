from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_prefix: str = "/api"
    database_url: str | None = None
    public_mcp_url: str = "http://127.0.0.1:49173/mcp"
    internal_mcp_url: str = "http://127.0.0.1:8000/mcp"
    mcp_test_timeout_seconds: float = 15.0
    workspace_host_root: Path = Path("/Users/conchi/workforce")
    workspace_container_root: Path = Path("/workspace")
    default_project_name: str | None = None
    default_agents_path: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="CONTEXT_ROUTER_",
        extra="ignore",
    )
