from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CONTEXT_ROUTER_", extra="ignore")

    database_url: str = "postgresql+psycopg://conchi:conchi123456@127.0.0.1:5432/context_router"


settings = Settings()
