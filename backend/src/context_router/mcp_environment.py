from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class McpEnvironmentSpec:
    tool_name: str
    title: str
    description: str
    environments: tuple[str, ...]
    built_in_default: str


MCP_ENVIRONMENT_SPECS: tuple[McpEnvironmentSpec, ...] = (
    McpEnvironmentSpec(
        tool_name="prepare_task_context",
        title="任务上下文准备",
        description="决定未显式指定环境的新任务使用哪套数据库映射和通用环境 JSON。",
        environments=("test", "uat"),
        built_in_default="uat",
    ),
    McpEnvironmentSpec(
        tool_name="read_middleware_context",
        title="实时中间件上下文",
        description="决定未显式指定环境时读取 default/local、TEST 或 UAT Nacos 配置档。",
        environments=("local", "test", "uat"),
        built_in_default="local",
    ),
)

MCP_ENVIRONMENT_SPEC_BY_TOOL = {spec.tool_name: spec for spec in MCP_ENVIRONMENT_SPECS}


def get_mcp_environment_spec(tool_name: str) -> McpEnvironmentSpec:
    spec = MCP_ENVIRONMENT_SPEC_BY_TOOL.get(tool_name)
    if spec is None:
        raise ValueError("这个 MCP 工具不支持 Workspace 默认环境")
    return spec


def require_mcp_environment(tool_name: str, environment: str) -> McpEnvironmentSpec:
    spec = get_mcp_environment_spec(tool_name)
    if environment not in spec.environments:
        choices = "、".join(item.upper() for item in spec.environments)
        raise ValueError(f"{tool_name} 的环境只能是 {choices}")
    return spec
