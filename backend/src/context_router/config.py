from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_prefix: str = "/api"
    workspace_host_root: Path = Path("/Users/conchi/workforce")
    workspace_container_root: Path = Path("/workspace")
    default_project_name: str | None = None
    default_agents_path: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="CONTEXT_ROUTER_",
        extra="ignore",
    )
