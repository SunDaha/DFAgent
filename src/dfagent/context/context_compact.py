import json
import time
from dfagent.base.messages import BaseMessage, AIMessages, HumanMessage, ToolMessage
from dfagent import KEEP_RECENT,PERSIST_THRESHOLD,TRANSCRIPT_DIR,TOOL_RESULTS_DIR
from dfagent.base.model import Model

_model = Model()

def snip_compact(messages: list[BaseMessage], max_messages: int = 50) -> list[BaseMessage]:
    """紧凑化消息列表。

    当 ``len(messages)`` 超过 ``max_messages`` 时，默认保留前 3 条（head）和后 ``max_messages-3`` 条（tail），
    中间的部分会被一条 ``HumanMessage`` 替代，内容形如 ``[snipped X messages]``。

    为了保持 ``assistant`` 与其 ``tool`` 调用的完整配对，进行以下两步扩展：
    1. **头部**：如果保留的最后一条是 ``assistant`` 且带有 ``tool_calls``，则继续向后包含所有紧随的 ``tool`` 消息。
    2. **尾部**：如果保留区的第一条是 ``tool``，则向前回溯，直到把产生这些 ``tool`` 调用的 ``assistant``（以及它的 ``tool_calls``）一起带进来。
    """
    if len(messages) <= max_messages:
        return messages

    # 默认保留 3 条头部，剩余放在尾部
    head_end = 3
    tail_start = len(messages) - (max_messages - 3)

    # -------- 头部扩展：确保 assistant 与其 tool 完整配对 --------
    if head_end > 0:
        last_head = messages[head_end - 1]
        if getattr(last_head, "role", None) == "assistant" and isinstance(last_head, AIMessages) and last_head.tool_calls:
            while head_end < len(messages) and getattr(messages[head_end], "role", None) == "tool":
                head_end += 1

    # -------- 尾部扩展：若首条是 tool，向前带上对应的 assistant --------
    if tail_start < len(messages) and getattr(messages[tail_start], "role", None) == "tool":
        # 向前回溯至该系列 tool 前的第一条非 tool（应为对应的 assistant）
        while tail_start > 0 and getattr(messages[tail_start - 1], "role", None) == "tool":
            tail_start -= 1
        # 若前面是 assistant，则一起保留
        if tail_start > 0 and getattr(messages[tail_start - 1], "role", None) == "assistant":
            tail_start -= 1

    # 计算被裁剪的消息数量
    snipped = max(0, tail_start - head_end)

    # 组装新消息列表
    new_messages: list[BaseMessage] = []
    new_messages.extend(messages[:head_end])
    if snipped > 0:
        new_messages.append(HumanMessage(content=f"[snipped {snipped} messages]"))
    new_messages.extend(messages[tail_start:])
    return new_messages


def micro_compact(messages: list[BaseMessage], keep_recent: int = KEEP_RECENT):
    """Micro‑compact：将 ``messages`` 中的 ``ToolMessage`` 按顺序收集，
    保留末尾最近的 ``keep_recent`` 条原样，其余更早的 ``ToolMessage``：
    若包含 ``"read"`` 工具调用则整条保留原内容，否则将全部 ``content``
    替换为占位符 ``"[Earlier tool result compacted. Re-run if needed.]"``，
    以缩减上下文占用。

    Args:
        messages: 待处理的完整消息列表（会被原地修改）。
        keep_recent: 保留末尾最近的 ``keep_recent`` 条 ``ToolMessage`` 的原 ``content``。

    Returns:
        修改后的 ``messages`` 列表（同一对象）。
    """
    # 1) 按出现顺序收集所有 ToolMessage 实例
    tool_messages: list[ToolMessage] = [m for m in messages if isinstance(m, ToolMessage)]

    # 2) 末尾最近 keep_recent 条原样保留（后续更新的内容更相关）；
    #    其余更早的按条处理：包含 read（读取文件内容）则整条保留，否则替换为占位符。
    placeholder = "[Earlier tool result compacted. Re-run if needed.]"
    compact_upto = max(0, len(tool_messages) - keep_recent)
    for tm in tool_messages[:compact_upto]:
        if "read" in (getattr(tm, "name", None) or []):
            continue
        # 保持 id/name 长度不变，仅替换 content 各项
        tm.content = [placeholder] * len(tm.content)

    return messages



def _persist_large_output(tool_id: str, content: str) -> str:
    """将大块 tool 输出写入本地文件并返回占位符字符串。

    文件路径: ``TOOL_RESULTS_DIR / f"{tool_id}.txt"``。
    写入后返回 ``"[Persisted tool result: {tool_id}.txt]"``，供后续序列化使用。
    """
    # 确保目录存在
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = TOOL_RESULTS_DIR / f"{tool_id}.txt"
    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        # 写入失败时仍返回原内容，避免后续破坏
        print(f"[WARN] persist tool result failed for {tool_id}: {e}")
        return content
    return f"[Persisted tool result: {file_path.name}]"


def tool_result_budget(messages:list[BaseMessage], max_bytes:int = 200000):
    """检查最近（即列表末尾）的 ``ToolMessage`` 总大小是否超过 ``max_bytes``。

    - 若没有 ``ToolMessage``，直接返回 ``messages``。
    - 若总字符数 ≤ ``max_bytes``，不做任何处理。
    - 若超过，则按单个 ``content`` 条目长度降序压缩：
        * 长度 ≤ ``PERSIST_THRESHOLD`` 的条目直接跳过（保留原内容）。
        * 其余条目调用 ``_persist_large_output`` 写入磁盘，并用返回的占位符替换对应的 ``content``。
    返回处理后的 ``messages``（原列表可能已被就地修改）。
    """
    # 1. 定位列表末尾的 ToolMessage（如果有）
    if not messages:
        return messages
    last_msg = messages[-1]
    if not isinstance(last_msg, ToolMessage):
        # 没有需要处理的 ToolMessage
        return messages

    # 2. 计算该 ToolMessage 中所有 content 条目的总字符数
    total = sum(len(str(c)) for c in last_msg.content)
    if total <= max_bytes:
        return messages

    # 3. 按 content 长度降序排序，获取原索引顺序
    indexed = list(enumerate(last_msg.content))
    indexed.sort(key=lambda p: len(str(p[1])), reverse=True)

    for idx, content in indexed:
        if total <= max_bytes:
            break
        if len(str(content)) <= PERSIST_THRESHOLD:
            continue
        # 对应的 tool id（保持顺序一致）
        tool_id = last_msg.id[idx] if idx < len(last_msg.id) else f"tool_{idx}"
        # 持久化并替换
        last_msg.content[idx] = _persist_large_output(tool_id, str(content))
        total = sum(len(str(c)) for c in last_msg.content)
    return messages


def _format_messages_readable(messages: list[BaseMessage]) -> str:
    """把消息列表转成简洁的可读文本（供 summarize_history 使用）。"""
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            parts.append(f"Human: {msg.content}")
        elif isinstance(msg, AIMessages):
            txt = msg.text if msg.text else (msg.content if isinstance(msg.content, str) else "")
            parts.append(f"Assistant: {txt}")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args_str = json.dumps(tc.args, ensure_ascii=False)
                    parts.append(f"  → ToolCall {tc.name}({args_str})")
        elif isinstance(msg, ToolMessage):
            for idx, tool_id in enumerate(msg.id):
                tool_name = msg.name[idx] if idx < len(msg.name) else ""
                content = msg.content[idx] if idx < len(msg.content) else ""
                parts.append(f"ToolResult ({tool_name}/{tool_id}): {content}")
        else:
            parts.append(str(msg))
    return "\n".join(parts)


def summarize_history(messages: list[BaseMessage]):
    """将对话历史格式化为可读文本，调用 LLM 生成结构化摘要。"""
    conversation = _format_messages_readable(messages)
    prompt = (
        "Summarize this coding-agent conversation so work can continue after context compression.\n"
        "Output in this EXACT format:\n\n"
        "## Current Task\n"
        "(one line: the task the agent is working on right now)\n\n"
        "## Completed\n"
        "- (file: what was done)\n"
        "- ...\n\n"
        "## Key Findings / Decisions\n"
        "- (finding or decision made, and why)\n"
        "- ...\n\n"
        "## Failed Attempts\n"
        "- (what was tried and did NOT work, and the reason — this prevents repeated mistakes)\n"
        "- ...\n\n"
        "## Next Steps\n"
        "- (concrete, actionable next step)\n"
        "- ...\n\n"
        "## User Constraints\n"
        "- (explicit constraints, preferences, or rules the user stated)\n"
        "- ...\n\n"
        "Be compact but concrete. Do NOT omit failed attempts — they are as important as successes.\n"
        "Do NOT omit user constraints — they must be followed when work resumes.\n\n"
        f"{conversation}"
    )
    ai_msg = _model.chat([HumanMessage(content=prompt)], max_tokens=4000)
    summary = getattr(ai_msg, "text", "")
    return (summary or "").strip() or "(empty summary)"

def write_transcript(messages):
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path


def compact_history(messages: list[BaseMessage]):
    """压缩对话历史：保留系统消息、首条用户消息以及最近 3 轮完整对话，
    中间部分使用 LLM 摘要替代。结构示例：
        [system] [首条 user] [摘要（HumanMessage）] [尾部最近 3 轮对话]
    """
    # 将完整对话写入 transcript（调试/审计用途）
    _ = write_transcript(messages)

    # 保留头部 (系统 + 首条用户)
    head: list[BaseMessage] = []
    idx = 0
    # 连续的 system 消息全部保留
    while idx < len(messages) and getattr(messages[idx], "role", None) == "system":
        head.append(messages[idx])
        idx += 1
    # 紧随其后的第一条 user 消息（如果存在）
    if idx < len(messages) and getattr(messages[idx], "role", None) == "user":
        head.append(messages[idx])
        idx += 1

    # 保留尾部最近 3 轮对话
    # 一轮对话 = 一条 user 消息及其后的 assistant/tool 消息。
    # 从末尾向前数第 3 条 user 消息，作为尾部起点。
    tail_start = len(messages)
    user_count = 0
    for i in range(len(messages) - 1, idx - 1, -1):
        if getattr(messages[i], "role", None) == "user":
            user_count += 1
            if user_count >= 3:
                tail_start = i
                break
    # 若 user 消息不足 3 条，尾部从 idx 之后开始（即全部保留剩余内容）
    if user_count < 3:
        tail_start = idx
    tail = messages[tail_start:]

    # 中间区域需要摘要
    middle = messages[idx:tail_start]
    summary_text = summarize_history(middle) if middle else ""

    # 用摘要生成一条 HumanMessage 替代中间内容
    summary_msg = HumanMessage(content=f"[Compacted — earlier context summarized]\n\n{summary_text}")

    # 合成新的消息列表
    new_messages: list[BaseMessage] = []
    new_messages.extend(head)
    new_messages.append(summary_msg)
    new_messages.extend(tail)
    return new_messages
