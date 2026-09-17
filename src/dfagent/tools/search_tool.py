"""MCP 工具搜索入口。"""

import json

from dfagent.mcp.mcp_handler import search_mcp_tools
from dfagent.tools.tool import tool


@tool(name="search_tool")
def search_tool(
    query: str = "", server: str | None = None, limit: int = 10
) -> str:
    """搜索可用的 MCP 工具，只返回元信息，不会加载或执行工具。

    Args:
        query: 工具名、描述或 MCP 服务名中的关键词；为空时返回全部工具。
        server: 可选的 MCP 服务名过滤条件。
        limit: 最多返回的工具数量，范围为 1 到 100。
    """
    results = search_mcp_tools(query=query, server=server, limit=limit)
    return json.dumps(results, ensure_ascii=False)
