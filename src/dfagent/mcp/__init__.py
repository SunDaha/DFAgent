"""MCP 公共 API。

处理器相关符号采用惰性导出，避免 ``app_state_store`` 初始化期间的循环导入。
"""

from dfagent.mcp.mcp_client import (
    MCPClient,
    MCPConnectError,
    MCPError,
    MCPNotConnectedError,
    MCPTimeoutError,
)
from dfagent.mcp.mcp_discovery import (
    MCPDiscovery,
    MCPServerSpec,
    default_config_paths,
    discover_specs,
    ensure_mcp_config,
    load_jsonc,
    strip_json_comments,
)

_HANDLER_EXPORTS = (
    "MCPTOOLMAP",
    "ensure_mcp_discovered",
    "execute_mcp_tool",
    "get_all_mcp_tools",
    "get_loaded_mcp_tool_infos",
    "get_mcp_tools",
    "list_tools",
    "load_mcp_tool",
    "mcp_tool_to_tool_info",
    "search_mcp_tools",
    "to_tool_infos",
    "tools_to_tool_infos",
)


def __getattr__(name: str):
    if name in _HANDLER_EXPORTS:
        from dfagent.mcp import mcp_handler

        return getattr(mcp_handler, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MCPClient",
    "MCPError",
    "MCPConnectError",
    "MCPTimeoutError",
    "MCPNotConnectedError",
    "MCPDiscovery",
    "MCPServerSpec",
    "discover_specs",
    "default_config_paths",
    "ensure_mcp_config",
    "load_jsonc",
    "strip_json_comments",
    *_HANDLER_EXPORTS,
]
