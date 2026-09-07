"""Message 类型定义：Human / AI / Tool，统一继承 BaseMessage。

提供三种序列化：
  - to_dict()       通用字典
  - to_openai()     OpenAI API 消息格式
  - to_anthropic()  Anthropic API 消息格式（单条）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class BaseMessage:
    role: str
    
    def get_role(self):
        return self.role
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # --- 平台适配（子类覆盖） ---
    def to_openai(self) -> dict[str, Any]:
        """默认直接返回 to_dict()"""
        return self.to_dict()

    def to_anthropic(self) -> dict[str, Any]:
        """默认直接返回 to_dict()"""
        return self.to_dict()

@dataclass
class SystemMessage(BaseMessage):
    role: str = "system"
    content: str = ""
    
    def __init__(self, content: str) -> None:
        self.content = content
    
    def to_dict(self) -> dict[str,Any]:
        return {"role":"system","content":self.content}

@dataclass
class HumanMessage(BaseMessage):
    """用户消息。"""
    role: str = "user"
    content: str | list[dict[str,Any]] = ""

    def __init__(self, content: str | list[dict[str,Any]]) -> None:
        self.content = content
        
    def to_dict(self):
        return {"role":"user","content":self.content}



@dataclass
class ToolCall:
    id:str
    name:str
    args:dict[str,Any]
    
    def get_name(self):
        return self.name
    
    def get_args(self):
        return self.args
    
    
    
@dataclass
class AIMessages(BaseMessage):
    """LLM 回答消息"""
    role: str = "assistant"
    content: str | list[dict[str,Any]] = ""
    text: str = ""
    id: str = ""
    tool_calls: list[ToolCall] | None = None
    
    def get_tool_calls(self):
        return self.tool_calls
    
    def get_content(self):
        return self.content
    
    def get_text(self):
        return self.text
    
    def to_openai(self) -> dict[str, Any]:
        """将 AIMessages 转换为 OpenAI 消息结构。

        - content 直接保留（可以是字符串或 block 列表）
        - 若有 tool_calls，将每个 ToolCall 转成 OpenAI function‑call 格式
        """
        data: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            # 将 ToolCall 实例转换为 OpenAI 所需的 dict
            openai_calls = []
            for tc in self.tool_calls:
                # tc.args 需要序列化为 JSON 字符串
                openai_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args, ensure_ascii=False),
                        },
                    }
                )
            data["tool_calls"] = openai_calls
        return data

    def to_anthropic(self) -> dict[str, Any]:
        """将 AIMessages 转换为 Anthropic 单条消息结构。

        - text content 合并为一个 text block（如果是字符串）
        - 每个 ToolCall 直接转为 tool_use block
        """
        blocks: list[dict[str, Any]] = []
        if isinstance(self.content, str) and self.content:
            blocks.append({"type": "text", "text": self.content})
        # 如果 content 本身已经是 block 列表（如从 Anthropic 原始消息反序列化），直接使用
        elif isinstance(self.content, list):
            blocks.extend(self.content)
        if self.tool_calls:
            for tc in self.tool_calls:
                # tc.args 已是 dict，直接作为 tool_use 的 input
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.args,
                })
        return {"role": "assistant", "content": blocks}



class ToolMessage(BaseMessage):
    """是多个工具调用结果的列表"""
    role: str = "tool"
    id: list[str] = field(default_factory=list)      # 工具ID
    name: list[str] = field(default_factory=list)    # 工具名字（与 id 一一对应，不参与转换）
    content: list[str] = field(default_factory=list)  # 工具结果
    
    
    def __init__(self, id, name, content):
        self.id = id
        self.name = name
        self.content = content
        
    def to_openai(self):
        result = []
        for i in range(len(self.id)):
            result.append(
                {"role":"tool",
                 "tool_call_id":self.id[i],
                 "content":self.content[i]
                })
        return result
    def to_anthropic(self):
        result = []
        for i in range(len(self.id)):
            result.append(
                {"type": "tool_result", 
                 "tool_use_id": self.id[i],
                 "content":self.content[i]
                }) 
        return {"role":"user","content":result}
        
    


class MessagesAnalysis:
    """将messages里面的所有数据解析成class"""

    @staticmethod
    def response_to_aimessage_openai(response: dict) -> AIMessages:
        """将单次 OpenAI Chat Completion 响应字典转换为 ``AIMessages``。

        只取第一条 choice 中的 ``message``，解析 ``content`` 与 ``tool_calls``，
        并返回对应的 ``AIMessages`` 实例。
        """
        # OpenAI ChatCompletion response 示例结构:
        # {"choices": [{"message": {"role": "assistant", "content": "...", "tool_calls": [...]}}]}
        choices = response.get("choices", [])
        if not choices:
            raise ValueError("OpenAI response contains no choices")
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        # 解析 tool_calls（如果有）
        tool_calls_raw = msg.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for tc in tool_calls_raw:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), args=args))
        text = content if isinstance(content, str) else ""
        return AIMessages(
            content=content,
            text=text,
            id=tool_calls[0].id if tool_calls else "",
            tool_calls=tool_calls or None,
        )

    @staticmethod
    def response_to_aimessage_anthropic(response: dict) -> AIMessages:
        """将单次 Anthropic 完整响应（即 ``assistant`` 角色的消息）转换为 ``AIMessages``。

        ``response`` 预期包含 ``role``、``content``（block 列表）等字段。
        将 ``text`` block 合并为 ``text`` 字段，``tool_use`` block 转为 ``ToolCall`` 列表。
        """
        # Anthropic response 示例结构:
        # {"role": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]}
        role = response.get("role")
        if role != "assistant":
            raise ValueError("Anthropic response role is not assistant")
        content_blocks = response.get("content", [])
        if not isinstance(content_blocks, list):
            content_blocks = []
        text = ""
        tool_calls: list[ToolCall] = []
        for block in content_blocks:
            btype = block.get("type")
            if btype == "text":
                text += block.get("text", "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        args=block.get("input", {}),
                    )
                )
        # 对于 Anthropic，content 直接保留原始 block 列表
        return AIMessages(
            content=content_blocks,
            text=text,
            id=tool_calls[0].id if tool_calls else "",
            tool_calls=tool_calls or None,
        )


    @staticmethod
    def openai_dict_to_BaseMessages(messages):
        """解析 OpenAI 格式消息 dict 列表为消息对象。

        连续 role="tool" 的消息合并为一个 ToolMessage；
        ToolMessage.name 通过 id 回查上一个 AIMessages 的 tool_calls 得到。
        """
        result = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")
            if role == "system":
                result.append(SystemMessage(str(msg.get("content", ""))))
                i += 1
            elif role == "user":
                result.append(HumanMessage(msg.get("content", "")))
                i += 1
            elif role == "assistant":
                content = msg.get("content", "")
                tool_calls = []
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    tool_calls.append(
                        ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), args=args)
                    )
                text = content if isinstance(content, str) else ""
                result.append(
                    AIMessages(
                        content=content,
                        text=text,
                        id=tool_calls[0].id if tool_calls else "",
                        tool_calls=tool_calls or None,
                    )
                )
                i += 1
            elif role == "tool":
                ids, contents = [], []
                while i < len(messages) and messages[i].get("role") == "tool":
                    m = messages[i]
                    ids.append(m.get("tool_call_id", ""))
                    contents.append(MessagesAnalysis._to_str(m.get("content", "")))
                    i += 1
                tm = ToolMessage(id=ids, content=contents, name=MessagesAnalysis._find_tool_name(result, ids))
                result.append(tm)
            else:
                i += 1
        return result

    @staticmethod
    def anthropic_dict_to_BaseMessages(messages:list):
        """解析 Anthropic 格式消息 dict 列表为消息对象。

        assistant 的 tool_use block 转为 ToolCall；
        user 消息中的 tool_result blocks 合并为一个 ToolMessage。
        """
        result = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", [])
            if not isinstance(content, list):
                content = []
            if role == "system":
                sys_content = msg.get("content", "")
                if not isinstance(sys_content, str):
                    # block 列表：只取 text block，合并成字符串
                    sys_content = "".join(
                        b.get("text", "") for b in sys_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                result.append(SystemMessage(sys_content))
            elif role == "assistant":
                text = ""
                tool_calls = []
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        text += block.get("text", "")
                    elif btype == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                id=block.get("id", ""),
                                name=block.get("name", ""),
                                args=block.get("input", {}),
                            )
                        )
                result.append(
                    AIMessages(
                        content=content,
                        text=text,
                        id=tool_calls[0].id if tool_calls else "",
                        tool_calls=tool_calls or None,
                    )
                )
            elif role == "user":
                tool_results = [b for b in content if b.get("type") == "tool_result"]
                if tool_results:
                    ids = [b.get("tool_use_id", "") for b in tool_results]
                    contents = [
                        MessagesAnalysis._to_str(b.get("content", ""))
                        for b in tool_results
                    ]
                    tm = ToolMessage(id=ids, content=contents, name=MessagesAnalysis._find_tool_name(result, ids))
                    result.append(tm)
                else:
                    text = "".join(
                        b.get("text", "") for b in content if b.get("type") == "text"
                    )
                    result.append(HumanMessage(text))
            # 其他 role 忽略
        return result

    @staticmethod
    def openai_BaseMessages_to_dict(messages:list[BaseMessage])-> list[dict]:
        """将 list[BaseMessage] 序列化为可直接传给 OpenAI 的 list[dict]。

        逐条调用 to_openai()；
        ToolMessage.to_openai() 返回多条 role=tool 消息，需展平进列表。
        """
        result: list[dict] = []
        for m in messages:
            data = m.to_openai()
            if isinstance(data, list):
                result.extend(data)
            else:
                result.append(data)
        return result

    @staticmethod
    def anthropic_BaseMessages_to_dict(messages:list[BaseMessage])->list[dict]:
        """将 list[BaseMessage] 序列化为可直接传给 Anthropic 的 list[dict]。

        逐条调用 to_anthropic()；
        ToolMessage.to_anthropic() 把整组工具结果包在一条 role=user 消息里，直接追加即可。
        """
        result: list[dict] = []
        for m in messages:
            data = m.to_anthropic()
            if isinstance(data, list):
                result.extend(data)
            else:
                result.append(data)
        return result
    
    @staticmethod
    def _to_str(value) -> str:
        """把工具结果（str / list / dict）统一转为字符串。"""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _find_tool_name(parsed, tool_ids: list) -> list:
        """向上查找最近的 AIMessages，按 id 逐个匹配 tool_calls 得到工具名。

        返回与 ``tool_ids`` 一一对应的 ``list[str]``，找不到的 id 记为空串。
        """
        names = []
        for tid in tool_ids:
            name = ""
            for m in reversed(parsed):
                if isinstance(m, AIMessages) and m.tool_calls:
                    for tc in m.tool_calls:
                        if tc.id == tid:
                            name = tc.name
                            break
                    if name:
                        break
            names.append(name)
        return names
    

