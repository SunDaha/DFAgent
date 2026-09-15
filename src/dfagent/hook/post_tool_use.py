from dfagent.base.messages import ToolMessage
from dfagent import MAX_TOOL_OUTPUR_SIZE,WORKDIR

def large_output_hook(tool_message: ToolMessage) -> None:
    for index, content in enumerate(tool_message.content):
        if len(str(content)) >= MAX_TOOL_OUTPUR_SIZE:
            tool_message.content[index] = (
                "This tool output exceeds maximum output size"
            )