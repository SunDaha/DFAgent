from enum import Enum
from typing import Callable



class HookEvent(Enum):
    """钩子事件类型。"""
    DeBug = "DeBug" # 调试钩子
    SessionStart = "SeessionStart" # 回话开始
    UserPromptSubmit = "UserPromptSubmit" # 用户提示词输入钩子
    PreToolUse = "PreToolUse" # 工具调用前钩子
    PostToolUse = "PostToolUse" # 工具调用后钩子
    Stop = "Stop"

HOOKS: dict[HookEvent, list[Callable]] = {
    HookEvent.DeBug: [],
    HookEvent.SessionStart: [],
    HookEvent.UserPromptSubmit: [],
    HookEvent.PreToolUse: [],
    HookEvent.PostToolUse: [],
    HookEvent.Stop: [],
}


def register_hook(event: HookEvent, func: Callable) -> None:
    """注册一个钩子函数到指定事件。"""
    if event not in HookEvent:
        raise ValueError(f"Unknown event: {event}")
    HOOKS[event].append(func)


def trigger_hooks(event: HookEvent, *args, **kwargs) -> str | None:
    """触发指定事件的所有钩子函数"""
    if event not in HookEvent:
        raise ValueError(f"Unknown event: {event}")
    for func in HOOKS[event]:
        result = func(*args, **kwargs)
        if result is not None:
            return str(result)
    return None


## 注册钩子
from dfagent.hook.pre_tool_use import permission_check_hook, log_hook
from dfagent.hook.post_tool_use import large_output_hook
from dfagent.hook.de_bug import print_messages

register_hook(HookEvent.PreToolUse, permission_check_hook)
register_hook(HookEvent.PreToolUse, log_hook)
register_hook(HookEvent.PostToolUse, large_output_hook)
register_hook(HookEvent.DeBug, print_messages)




