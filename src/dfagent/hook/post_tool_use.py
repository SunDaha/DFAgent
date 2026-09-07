from dfagent.base.messages import ToolCall

def large_output_hook(tool_calll: ToolCall, output) -> None:
    """PostToolUse: 大输出警告钩子。"""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] ⚠ Large output from {tool_calll.get_name()}: {len(str(output))} chars\033[0m")
    return None