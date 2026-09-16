from dfagent.app_state_store import mcp_discovery
from dfagent.mcp.mcp_discovery import MCPDiscovery
from dfagent.mcp.mcp_client import MCPClient
from typing import Any
from dfagent.tools.tool_model import ToolInfo
from dfagent.tools.tool import convert_anthropic_tool, convert_openai_tool

def reload_mcp(function:callable):
    mcp_discovery.discover()
    return function


# ---------------------------------------------------------------- ToolInfo 转换


def mcp_tool_to_tool_info(
    client: MCPClient, tool_def: dict, return_direct: bool = True
) -> ToolInfo:
    """把单个 MCP 工具（client.tools 里的 dict）转成 ToolInfo。

    参数校验交给 MCP 服务端（call_tool 会拿到服务端的 is_error），
    因此 args_schema 留空，避免与任意 input_schema 做二次、不完整的校验。
    """
    name = tool_def["name"]
    description = tool_def.get("description") or ""
    input_schema = tool_def.get("input_schema") or tool_def.get("inputSchema") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}
    properties = input_schema.get("properties", {}) or {}
    required = input_schema.get("required", []) or []

    def _invoke(**kwargs: Any) -> str:
        # 直接透传给 MCP 服务端，由它校验并返回结果文本
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
    """把某个客户端已发现的全部工具转成 ToolInfo 列表。"""
    return [mcp_tool_to_tool_info(client, tool, return_direct) for tool in client.tools]

def list_tools(self) -> dict[str, list[dict]]:
        """返回 {服务名: 工具列表} 快照。"""
        return {name: list(client.tools) for name, client in self.clients.items()}

def to_tool_infos(self, return_direct: bool = True) -> list[ToolInfo]:
    """把全部已发现工具转成 ToolInfo，供注册进 TOOL_REGISTRY 或直接喂给 Agent。"""
    infos: list[ToolInfo] = []
    for client in self.clients.values():
        infos.extend(tools_to_tool_infos(client, return_direct))
    return infos

# tool_name -> client
MCPTOOLMAP:dict[str,MCPClient] = {}


def execute_mcp_tool(tool_name:str, args:dict) -> str:
    if tool_name in MCPTOOLMAP:
        client = MCPTOOLMAP.get(tool_name)
        result = client.call_tool(tool_name,args)
        return result
    else:
        clients = mcp_discovery.clients.values()
        for client in clients:
            for tool in client.list_tools():
                MCPTOOLMAP[tool["name"]] = client
    client = MCPTOOLMAP.get(tool_name, "")
    if not client:
        return f"Error: {tool_name} not found"
    result = client.call_tool(tool_name,args)
    return result

@reload_mcp
def get_mcp_tools(mcp_name:str) -> list[ToolInfo]:
    client = mcp_discovery.get_client(mcp_name)
    return tools_to_tool_infos(client)



@reload_mcp
def get_all_mcp_tools()-> list[ToolInfo]:
    # 重新加载一遍
    return to_tool_infos()
