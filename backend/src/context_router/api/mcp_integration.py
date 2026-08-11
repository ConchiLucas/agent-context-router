from fastapi import APIRouter, Request

from context_router.schemas.mcp_integration import (
    McpIntegrationInfo,
    McpIntegrationTestRequest,
    McpIntegrationTestResult,
)
from context_router.services.mcp_integration import McpIntegrationService

router = APIRouter(prefix="/mcp/integration", tags=["mcp-integration"])


def _service(request: Request) -> McpIntegrationService:
    return request.app.state.mcp_integration_service


@router.get("", response_model=McpIntegrationInfo)
def get_mcp_integration(request: Request) -> McpIntegrationInfo:
    return _service(request).get_info()


@router.get("/tools")
async def list_mcp_tools(request: Request) -> dict[str, object]:
    tools = await request.app.state.mcp_server.list_tools()
    return {
        "tools": [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools
        ]
    }


@router.post("/tests", response_model=McpIntegrationTestResult)
async def test_mcp_integration(
    payload: McpIntegrationTestRequest,
    request: Request,
) -> McpIntegrationTestResult:
    return await _service(request).run_test(payload.workspace_id)
