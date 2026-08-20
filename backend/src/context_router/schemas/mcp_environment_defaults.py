from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

McpEnvironment = Literal["local", "test", "uat"]
McpEnvironmentDefaultSource = Literal["configured", "built_in"]


class McpEnvironmentOption(BaseModel):
    value: McpEnvironment
    label: str


class McpEnvironmentToolDefault(BaseModel):
    tool_name: str
    title: str
    description: str
    environments: list[McpEnvironmentOption]
    default_environment: McpEnvironment
    source: McpEnvironmentDefaultSource


class WorkspaceMcpEnvironmentDefaults(BaseModel):
    workspace_id: str
    tools: list[McpEnvironmentToolDefault]


class McpEnvironmentDefaultUpdate(BaseModel):
    environment: McpEnvironment
