from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXT_ROUTER_", extra="ignore")

    database_url: str = "sqlite:///./context_router.db"


settings = Settings()
