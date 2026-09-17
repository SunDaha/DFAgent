"""MCP 工具动态加载入口。"""

import json

from dfagent.mcp.mcp_handler import load_mcp_tool
from dfagent.tools.tool import tool


@tool(name="load_tool")
def load_tool(name: str, server: str | None = None) -> str:
    """按名称加载 MCP 工具，并将其注册为当前 Agent 可调用的工具。

    Args:
        name: 要加载的 MCP 工具名称。
        server: 可选的 MCP 服务名；同名工具存在于多个服务时必须指定。
    """
    result = load_mcp_tool(tool_name=name, server=server)
    return json.dumps(result, ensure_ascii=False)
