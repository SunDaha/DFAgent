"""MCP 工具发现、转换、动态加载和执行。"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from dfagent.app_state_store import TOOL_REGISTRY, mcp_discovery
from dfagent.mcp.mcp_client import MCPClient
from dfagent.mcp.mcp_discovery import MCPDiscovery
from dfagent.tools.tool import convert_anthropic_tool, convert_openai_tool
from dfagent.tools.tool_model import ToolInfo


# 仅加载成功的 MCP 工具才会写入该映射。
MCPTOOLMAP: dict[str, MCPClient] = {}
_LOADED_MCP_TOOLS: dict[str, str] = {}
_DISCOVERY_INITIALIZED = False


def ensure_mcp_discovered(*, force: bool = False) -> MCPDiscovery:
    """确保全局 MCP 服务已发现，避免每次搜索都重复连接服务。"""
    global _DISCOVERY_INITIALIZED
    if force or not _DISCOVERY_INITIALIZED:
        mcp_discovery.discover()
        _DISCOVERY_INITIALIZED = True
    _rebuild_tool_map()
    return mcp_discovery


def reload_mcp(function: Callable) -> Callable:
    """兼容旧接口的装饰器：调用函数前确保 MCP 已发现。"""
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any):
        ensure_mcp_discovered()
        return function(*args, **kwargs)
    return wrapper


def _tool_input_schema(tool_def: dict) -> dict:
    schema = tool_def.get("input_schema") or tool_def.get("inputSchema") or {}
    return schema if isinstance(schema, dict) else {}


def _rebuild_tool_map() -> None:
    """刷新已加载工具的客户端索引，不把“已发现”误当成“已加载”。"""
    for name, server_name in list(_LOADED_MCP_TOOLS.items()):
        client = mcp_discovery.clients.get(server_name)
        if client is None or not any(
            tool.get("name") == name for tool in client.tools
        ):
            _LOADED_MCP_TOOLS.pop(name, None)
            MCPTOOLMAP.pop(name, None)
            # 发现结果已失效时移除对应的动态注册，避免后续调用使用旧客户端。
            TOOL_REGISTRY.pop(name, None)
        else:
            MCPTOOLMAP[name] = client


def mcp_tool_to_tool_info(
    client: MCPClient, tool_def: dict, return_direct: bool = True
) -> ToolInfo:
    """把单个 MCP 工具定义转换为本项目的 ``ToolInfo``。"""
    name = tool_def["name"]
    description = tool_def.get("description") or ""
    input_schema = _tool_input_schema(tool_def)
    properties = input_schema.get("properties", {}) or {}
    required = input_schema.get("required", []) or []
    if not isinstance(properties, dict):
        properties = {}
    if not isinstance(required, list):
        required = []

    def _invoke(**kwargs: Any) -> str:
        # 参数校验交给 MCP 服务端，避免对任意 input_schema 做二次校验。
        return client.call_tool(name, kwargs)

    return ToolInfo(
        name=name,
        description=description,
        function=_invoke,
        openai_def=convert_openai_tool(name, description, properties, required),
        anthropic_def=convert_anthropic_tool(name, description, properties, required),
        return_direct=return_direct,
        args_schema=None,
    )


def tools_to_tool_infos(
    client: MCPClient, return_direct: bool = True
) -> list[ToolInfo]:
    """把某个客户端已发现的全部工具转换为 ``ToolInfo`` 列表。"""
    return [
        mcp_tool_to_tool_info(client, tool, return_direct)
        for tool in client.tools
        if isinstance(tool, dict) and tool.get("name")
    ]


def list_tools(discovery: MCPDiscovery | None = None) -> dict[str, list[dict]]:
    """返回 ``{服务名: 工具列表}`` 快照。"""
    discovery = discovery or ensure_mcp_discovered()
    return {
        name: [dict(tool) for tool in client.tools]
        for name, client in discovery.clients.items()
    }


def to_tool_infos(
    discovery: MCPDiscovery | None = None, return_direct: bool = True
) -> list[ToolInfo]:
    """把全部已发现工具转换为 ``ToolInfo`` 列表。"""
    discovery = discovery or ensure_mcp_discovered()
    infos: list[ToolInfo] = []
    for client in discovery.clients.values():
        infos.extend(tools_to_tool_infos(client, return_direct))
    return infos


def _iter_tool_defs():
    for server_name, client in mcp_discovery.clients.items():
        for tool_def in client.tools:
            if isinstance(tool_def, dict) and isinstance(tool_def.get("name"), str):
                yield server_name, client, tool_def


def search_mcp_tools(
    query: str = "", server: str | None = None, limit: int = 20
) -> list[dict]:
    """搜索 MCP 工具元信息，不加载工具。"""
    ensure_mcp_discovered()
    query_text = str(query or "").strip().casefold()
    server_text = str(server or "").strip().casefold()
    try:
        max_results = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        max_results = 20

    results: list[dict] = []
    for server_name, _client, tool_def in _iter_tool_defs():
        description = str(tool_def.get("description") or "")
        tool_name = tool_def["name"]
        if server_text and server_text not in server_name.casefold():
            continue
        haystack = " ".join((tool_name, description, server_name)).casefold()
        if query_text and query_text not in haystack:
            continue
        results.append({
            "name": tool_name,
            "server": server_name,
            "description": description,
            "input_schema": _tool_input_schema(tool_def),
            "loaded": _LOADED_MCP_TOOLS.get(tool_name) == server_name,
        })
        if len(results) >= max_results:
            break
    return results


def _find_mcp_tool(tool_name: str, server: str | None = None):
    candidates = [
        item for item in _iter_tool_defs()
        if item[2].get("name") == tool_name and (not server or item[0] == server)
    ]
    if not candidates:
        return None, f"Error: MCP tool {tool_name!r} not found"
    if len(candidates) > 1:
        servers = ", ".join(item[0] for item in candidates)
        return None, (
            f"Error: MCP tool {tool_name!r} is ambiguous; "
            f"specify server: {servers}"
        )
    return candidates[0], None


def load_mcp_tool(
    tool_name: str, server: str | None = None, return_direct: bool = True
) -> dict:
    """加载并注册一个 MCP 工具，返回状态和工具 schema。"""
    ensure_mcp_discovered()
    found, error = _find_mcp_tool(tool_name, server)
    if error:
        return {"loaded": False, "error": error}

    server_name, client, tool_def = found
    registered_server = _LOADED_MCP_TOOLS.get(tool_name)
    existing = TOOL_REGISTRY.get(tool_name)
    if registered_server is not None:
        if registered_server != server_name:
            return {
                "loaded": False,
                "error": (
                    f"Error: tool {tool_name!r} is already loaded from "
                    f"server {registered_server!r}"
                ),
            }
        info = existing or mcp_tool_to_tool_info(client, tool_def, return_direct)
    else:
        if existing is not None:
            return {
                "loaded": False,
                "error": (
                    f"Error: tool name {tool_name!r} conflicts with "
                    "a registered local tool"
                ),
            }
        info = mcp_tool_to_tool_info(client, tool_def, return_direct)
        TOOL_REGISTRY[tool_name] = info
        MCPTOOLMAP[tool_name] = client
        _LOADED_MCP_TOOLS[tool_name] = server_name

    return {
        "loaded": True,
        "name": tool_name,
        "server": server_name,
        "description": info.description,
        "input_schema": _tool_input_schema(tool_def),
        "openai_def": info.openai_def,
        "anthropic_def": info.anthropic_def,
    }


def get_loaded_mcp_tool_infos(return_direct: bool = True) -> list[ToolInfo]:
    """返回已加载 MCP 工具的 ``ToolInfo``，供 Agent 刷新模型 schema。"""
    infos: list[ToolInfo] = []
    for name, server_name in _LOADED_MCP_TOOLS.items():
        client = mcp_discovery.clients.get(server_name)
        if client is None:
            continue
        tool_def = next(
            (tool for tool in client.tools if tool.get("name") == name), None
        )
        if tool_def is not None:
            infos.append(mcp_tool_to_tool_info(client, tool_def, return_direct))
    return infos


def execute_mcp_tool(tool_name: str, args: dict) -> str:
    """执行 MCP 工具；直接调用该底层 API 时会按名称自动加载。"""
    ensure_mcp_discovered()
    client = MCPTOOLMAP.get(tool_name)
    if client is None:
        loaded = load_mcp_tool(tool_name)
        if not loaded.get("loaded"):
            return str(loaded.get("error") or f"Error: {tool_name} not found")
        client = MCPTOOLMAP.get(tool_name)
    if client is None:  # pragma: no cover - 防御性兜底
        return f"Error: {tool_name} not loaded"
    return client.call_tool(tool_name, args)


@reload_mcp
def get_mcp_tools(mcp_name: str) -> list[ToolInfo]:
    client = mcp_discovery.get_client(mcp_name)
    return tools_to_tool_infos(client) if client is not None else []


@reload_mcp
def get_all_mcp_tools() -> list[ToolInfo]:
    return to_tool_infos(mcp_discovery)
