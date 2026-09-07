"""调试打印：把 agent 循环中的 messages 列表结构可视化。

``print_messages`` 每条消息一行，按角色着色，内容截断，
用于快速扫一眼循环各轮的消息样貌，不打印全量内容。
"""
from dfagent.base.messages import (
    BaseMessage,
    HumanMessage,
    AIMessages,
    ToolMessage,
    SystemMessage,
)

# 颜色
_C = {
    "system": "\033[90m",    # 灰
    "human": "\033[36m",     # 青
    "ai": "\033[32m",        # 绿
    "tool": "\033[33m",      # 黄
    "reset": "\033[0m",
}


def _truncate(text, limit: int = 80) -> str:
    """超长文本截断，换行符压成空格。"""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _line(color: str, label: str, content: str) -> str:
    return f"{color}{label}: {_truncate(content)}{_C['reset']}"


def print_messages(messages: list[BaseMessage]) -> None:
    """打印 messages 列表：每条一行，按角色着色，内容截断。"""
    if not messages:
        print("(空消息列表)")
        return

    lines = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            lines.append(_line(_C["system"], "System", msg.content))
        elif isinstance(msg, HumanMessage):
            lines.append(_line(_C["human"], "Human", msg.content))
        elif isinstance(msg, AIMessages):
            text = msg.text if msg.text else msg.content
            extra = ""
            if msg.tool_calls:
                calls = []
                for tc in msg.tool_calls:
                    args = _truncate(str(tc.args), 10) if tc.args else ""
                    calls.append(f"{tc.name}({args})")
                extra = "  [tools:" + ",".join(calls) + "]"
            lines.append(_line(_C["ai"], "AIMessages", text) + extra)
        elif isinstance(msg, ToolMessage):
            # 多个工具结果，用 | 拼接 name，内容截 10 字符
            pairs = [
                f"{msg.name[i] if i < len(msg.name) else ''}={_truncate(msg.content[i] if i < len(msg.content) else '', 10)}"
                for i in range(len(msg.id))
            ]
            lines.append(_line(_C["tool"], "ToolMessage", " | ".join(pairs)))
        else:
            lines.append(f"{_C['system']}{type(msg).__name__}: {_truncate(msg)}{_C['reset']}")

    print("\n".join(lines))
