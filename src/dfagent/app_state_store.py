from dfagent.task.task_model import Task, TaskStatus
from dfagent.tools.tool_model import ToolInfo

#Tool
TOOL_REGISTRY: dict[str,ToolInfo] = {}




tasks = dict["task_id":Task] = {}
# {
#      agent_id:身份
#     "agent_ad22d2":"main"
# }
agent_name_registry:dict[str,str] = {}

