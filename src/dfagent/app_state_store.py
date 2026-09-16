from dfagent.tools.tool_model import ToolInfo
from dfagent.mcp.mcp_discovery import MCPDiscovery

#Tool
TOOL_REGISTRY: dict[str,ToolInfo] = {}

# MCP
mcp_discovery: MCPDiscovery = MCPDiscovery()

# Agent ID
# {
#      agent_id:身份
#     "agent_ad22d2":"main"
# }
agent_name_registry:dict[str,str] = {}