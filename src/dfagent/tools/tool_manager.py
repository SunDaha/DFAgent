from dfagent.tools import base_tools, context_retrieval, skills_tool, task_tools
from dfagent.base.messages import BaseMessage, ToolCall, ToolMessage, HumanMessage
from dfagent.base.tool_model import ToolInfo
from dfagent.hook.hooks import trigger_hooks, HookEvent
from dfagent.tools.background import BACKGROUND
from dfagent.app_state_store import TOOL_REGISTRY


# ToolStore 基本操作
def get_tools_list() -> list[ToolInfo]:
    return TOOL_REGISTRY.values()

def get_tool_info(name:str) -> ToolInfo:
    return TOOL_REGISTRY.get(name)


def get_tool_function(name:str):
    info = get_tool_info(name)
    if info:
        return info.function

def get_tool_schema(name:str):
    info = get_tool_info(name)
    if info:
        return info.args_schema




def get_base_tools() -> list[ToolInfo]:
    return [TOOL_REGISTRY["bash"],
            TOOL_REGISTRY["read"],
            TOOL_REGISTRY["write"],
            TOOL_REGISTRY["edit"],
            TOOL_REGISTRY["glob"],
            TOOL_REGISTRY["grep"]]

def get_todo_tools() -> list[ToolInfo]:
    return [TOOL_REGISTRY["write_todo"]]

def get_context_tools() -> list[ToolInfo]:
    return [TOOL_REGISTRY["retrieve_tool_result"]]

def get_skills_tools() -> list[ToolInfo]:
    return [TOOL_REGISTRY["load_skill"]]



def _should_run_background(tool_call:ToolCall) -> bool:
    return tool_call.name == "bash" and tool_call.args.get("run_in_background",False)


def inject_background_results(messages:list[BaseMessage]) -> int:
    notifications = BACKGROUND.collect()
    if not notifications:
        return 0
    
    result = [{"type": "text", "text": item} for item in notifications]
    if messages and messages[-1].role == "user":
        content = messages[-1].content
        if isinstance(content, list) :
            content.extend(result)
        else:
            messages[-1].content = [{"type": "text", "text": str(content)}, *result]
    else:
        messages.append(HumanMessage(content=result))

def execute_tool(tool_call:ToolCall) -> str:
    """执行一个工具
    Args:
        tool_call (ToolCall): 待执行的工具（来自 AI 消息解析）
    """
    tool_info = get_tool_info(tool_call.name)
    if tool_info is None:
        return f"Error: 未找到工具: {tool_call.name}"
    
    blocked = trigger_hooks(HookEvent.PreToolUse, tool_call)
    if blocked:
        return f"Blocked by hook: {blocked}"
    _, result = tool_info.execute(tool_call.args)
    return str(result)



def execute_batch_tool(agent, tool_calls: list[ToolCall]) -> ToolMessage:
    """执行一组工具调用，合并结果为一个 ToolMessage。

    对每个 ToolCall 查找注册的工具并校验、执行：
      - 工具不存在 → 结果记为错误文本
      - 校验/执行失败 → 结果记为错误文本（来自 ToolInfo.execute 的 (False, msg)）
      - 成功 → 结果转为字符串
    ToolMessage.id 为所有 tool_call id，content、name 与 id 一一对应。

    Args:
        tool_calls: 待执行的工具调用列表（来自 AI 消息解析）

    Returns:
        ToolMessage：一组工具执行结果
    """
    ids: list[str] = []
    names: list[str] = []
    contents: list[str] = []
    for tc in tool_calls:
        ids.append(tc.id)
        names.append(tc.name)
        
        # 获取tool_info
        tool_info = get_tool_info(tc.name)
        if not tool_info:
            contents.append(f"Error: 未找到工具: {tc.name}")
            continue
        
        # PreToolUse Hook
        blocked = trigger_hooks(HookEvent.PreToolUse, tc)
        if blocked:
            contents.append(f"Blocked by hook: {blocked}")
            continue
        
        if _should_run_background(tc):
            try:
                task_id = BACKGROUND.start(tool_call=tc, tool_info=tool_info)
                contents.append(f"[Background task {task_id} started],The result will be collected on a later turn.")
            except Exception as e:
                contents.append = f"Error: {e}"
            continue
        
        # 执行方法
        result = tool_info.execute(tc.args)
        contents.append(str(result))
        
        if tc.name == "write_todo": 
            agent.todo_active = True
            agent.rounds_since_todo = 0
        
    tool_message = ToolMessage(id=ids, name=names, content=contents)
    # PostToolUse Hook
    trigger_hooks(HookEvent.PostToolUse,tool_message)
    return tool_message