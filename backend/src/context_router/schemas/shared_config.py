from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SharedAiProvider(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    label: str
    type: str
    base_url: str = Field(validation_alias="baseUrl")
    api_key: str = Field(validation_alias="apiKey")
    model: str
    max_tokens: int = Field(validation_alias="maxTokens")
    voice: str = ""
    capabilities: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    active: bool = False


class SharedAiCenterConfiguration(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    active_provider_id: str = Field(validation_alias="activeProviderId")
    providers: list[SharedAiProvider] = Field(default_factory=list)


class SharedAiCatalog(BaseModel):
    configured_default_provider_id: str
    center_active_provider_id: str
    active_provider_id: str
    default_source: str
    default_recovered: bool = False
    notice: str | None = None
    revision: int
    providers: list[SharedAiProvider]


class SharedAiDefaultUpdate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)


class SharedDatabaseConnection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    name: str
    type: str
    environment: str = ""
    host: str
    port: int
    database: str
    username: str
    password: str = ""
    parameters: dict[str, str] = Field(default_factory=dict)


class SharedDatabaseConfiguration(BaseModel):
    databases: list[SharedDatabaseConnection] = Field(default_factory=list)


class SharedLocalCliItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    label: str
    enabled: bool = True
    command: str
    default_args: list[str] = Field(default_factory=list, validation_alias="defaultArgs")
    model: str = ""
    reasoning_effort: str = Field("", validation_alias="reasoningEffort")
    working_directory: str = Field("", validation_alias="workingDirectory")
    timeout_seconds: int = Field(0, validation_alias="timeoutSeconds")
    capabilities: list[str] = Field(default_factory=list)
    active: bool = False


class SharedLocalCliConfiguration(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    active_config_id: str = Field("", validation_alias="activeConfigId")
    configs: list[SharedLocalCliItem] = Field(default_factory=list)


class SharedObjectStorageConfiguration(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    configured: bool = False
    enabled: bool = False
    endpoint: str = ""
    access_key_id: str = Field("", validation_alias="accessKeyId")
    secret_access_key: str = Field("", validation_alias="secretAccessKey")
    use_ssl: bool = Field(False, validation_alias="useSsl")
    bucket_name: str = Field("", validation_alias="bucketName")
    base_path: str = Field("", validation_alias="basePath")


class SharedImageModelCatalog(BaseModel):
    active_provider_id: str
    providers: list[SharedAiProvider]


class SharedConfigurationCatalog(BaseModel):
    ai: SharedAiCatalog
    databases: list[SharedDatabaseConnection]
    local_cli: SharedLocalCliConfiguration
    object_storage: SharedObjectStorageConfiguration
    image_models: SharedImageModelCatalog
    runtime: dict[str, Any]
