from dfagent.base.messages import ToolMessage
from dfagent import MAX_TOOL_OUTPUR_SIZE,WORKDIR

def large_output_hook(tool_message:ToolMessage) -> None:
    """PostToolUse: 大输出警告钩子。"""
    for content in ToolMessage.content:
        if(str(content) >= MAX_TOOL_OUTPUR_SIZE):
            content = "This tool outpur exceeds maximum output"
            return None