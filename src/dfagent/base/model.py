"""统一 Model：屏蔽 OpenAI / Anthropic 差异，一律返回 AIMessages。"""
from __future__ import annotations

import json
from collections.abc import Iterator

from openai import OpenAI
from anthropic import Anthropic

from dfagent import client as _global_client, model as _global_model
from dfagent.base.messages import BaseMessage, AIMessages, MessagesAnalysis, StreamEvent

# OpenAI reasoning_effort 合法取值
_REASONING_EFFORT_ALLOWED = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
# Anthropic thinking budget_tokens：effort 档位 → 预算
_ANTHROPIC_EFFORT_BUDGET = {"low": 2048, "medium": 4096, "high": 8192}


class Model:
    """统一的对话模型封装。

    持有底层 client（``OpenAI`` 或 ``Anthropic`` 实例）与模型名，
    ``chat()`` 按 client 实例类型自动分流，输入统一为 ``list[BaseMessage]``，
    输出统一为 ``AIMessages``。
    """
    
    def __init__(self, 
                 client: OpenAI | Anthropic | None = None, 
                 model: str | None = None, 
                 tools:list[dict] | None = None,
                 thinking_effort:str | None = None,
                 ) -> None:
        self.client = client or _global_client
        self.model = model or _global_model
        self.tools = tools or []
        self.thinking_effort = thinking_effort
    def chat(self, messages: list[BaseMessage], max_tokens: int = 4096) -> AIMessages:
        """发起一次对话，返回 AIMessages。"""
        if isinstance(self.client, OpenAI):
            return self._chat_openai(messages, max_tokens)
        if isinstance(self.client, Anthropic):
            return self._chat_anthropic(messages, max_tokens)
        raise TypeError(
            f"Unsupported client type: {type(self.client).__name__}"
        )

    def stream_chat(
        self, messages: list[BaseMessage], max_tokens: int = 4096
    ) -> Iterator[StreamEvent]:
        """发起一次流式对话，逐块产出 ``StreamEvent``。

        - ``text`` / ``thinking`` 事件：正文与思考内容的增量片段
        - ``tool_call_delta`` 事件：工具调用参数的增量片段（JSON 未完整）
        - ``done`` 事件：流结束，``event.message`` 为聚合后的 ``AIMessages``，
          与 ``chat()`` 的返回值同构，可直接接入工具调用逻辑

        说明：本方法为生成器，异常在迭代过程中才抛出；调用方应包裹 ``try``。
        """
        if isinstance(self.client, OpenAI):
            yield from self._stream_openai(messages, max_tokens)
        elif isinstance(self.client, Anthropic):
            yield from self._stream_anthropic(messages, max_tokens)
        else:
            raise TypeError(
                f"Unsupported client type: {type(self.client).__name__}"
            )

    # --- 请求参数构建（chat / stream_chat 共用，避免两套分支走偏） ---

    def _build_openai_kwargs(self) -> dict:
        """构建 OpenAI 请求的可选参数（tools / reasoning_effort）。"""
        kwargs: dict = {}
        if self.tools:
            kwargs["tools"] = self.tools
        # 思考模式：仅当 effort 非 None 且值合法才开启 reasoning
        if self.thinking_effort is not None:
            if self.thinking_effort in _REASONING_EFFORT_ALLOWED:
                kwargs["reasoning_effort"] = self.thinking_effort
            else:
                print(f"[WARN] 无效 reasoning_effort: {self.thinking_effort}，已忽略")
        return kwargs

    def _build_anthropic_kwargs(self, max_tokens: int) -> dict:
        """构建 Anthropic 请求的可选参数（tools / thinking）。"""
        kwargs: dict = {}
        if self.tools:
            kwargs["tools"] = self.tools
        # 思考模式：effort 非 None 时按档位映射 budget_tokens；None 则不开启思考
        if self.thinking_effort is not None:
            budget = _ANTHROPIC_EFFORT_BUDGET.get(self.thinking_effort, 4096)
            # budget 必须 < max_tokens，否则 API 会拒
            if budget < max_tokens:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
            else:
                print(f"[WARN] thinking budget_tokens({budget}) 需小于 max_tokens({max_tokens})，本次未开启思考")
        return kwargs

    def _chat_openai(self, messages: list[BaseMessage], max_tokens: int) -> AIMessages:
        # ToolMessage.to_openai() 返回多条 role=tool 消息，需展平；直接 list 推导会产生嵌套列表
        payload = MessagesAnalysis.openai_BaseMessages_to_dict(messages)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                **self._build_openai_kwargs(),
            )
        except Exception as e:
            raise RuntimeError(
                f"OpenAI 调用失败 (model={self.model}): {e}"
            ) from e
        # OpenAI SDK 返回 pydantic ChatCompletion，先 model_dump 成 dict 再解析
        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        return MessagesAnalysis.response_to_aimessage_openai(data)

    def _chat_anthropic(self, messages: list[BaseMessage], max_tokens: int) -> AIMessages:
        payload = [m.to_anthropic() for m in messages]
        try:
            response = self.client.messages.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                **self._build_anthropic_kwargs(max_tokens),
            )
        except Exception as e:
            raise RuntimeError(
                f"Anthropic 调用失败 (model={self.model}): {e}"
            ) from e
        # Anthropic SDK 返回 pydantic Message，先 model_dump 成 dict 再解析
        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        return MessagesAnalysis.response_to_aimessage_anthropic(data)

    # --- 流式实现 ---

    def _stream_openai(
        self, messages: list[BaseMessage], max_tokens: int
    ) -> Iterator[StreamEvent]:
        """OpenAI 流式：累积 delta.content 与按 index 分组的 delta.tool_calls。"""
        payload = MessagesAnalysis.openai_BaseMessages_to_dict(messages)
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                stream=True,
                **self._build_openai_kwargs(),
            )
        except Exception as e:
            raise RuntimeError(
                f"OpenAI 调用失败 (model={self.model}): {e}"
            ) from e

        text_parts: list[str] = []
        # index -> {id, name, arguments}；arguments 是跨分片拼接的 JSON 字符串
        tool_buffers: dict[int, dict] = {}

        try:
            for chunk in stream:
                data = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                content = delta.get("content")
                if content:
                    text_parts.append(content)
                    yield StreamEvent(type="text", text=content)

                # 部分模型（如带 reasoning 的）会把思考内容放在该字段
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield StreamEvent(type="thinking", text=reasoning)

                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index", 0)
                    buf = tool_buffers.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    # id / name 只在首个分片出现，后续分片为 None，不可覆盖
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        buf["name"] = fn["name"]
                    args_delta = fn.get("arguments") or ""
                    buf["arguments"] += args_delta
                    if args_delta:
                        yield StreamEvent(
                            type="tool_call_delta",
                            index=index,
                            id=buf["id"],
                            name=buf["name"],
                            args_delta=args_delta,
                        )
        except Exception as e:
            raise RuntimeError(
                f"OpenAI 流式调用失败 (model={self.model}): {e}"
            ) from e

        # 复用非流式解析器：拼出等价的完整响应 dict，保证两侧结果同构
        tool_calls = [
            {
                "id": buf["id"],
                "type": "function",
                "function": {"name": buf["name"], "arguments": buf["arguments"]},
            }
            for _, buf in sorted(tool_buffers.items())
        ]
        message: dict = {"role": "assistant", "content": "".join(text_parts)}
        if tool_calls:
            message["tool_calls"] = tool_calls
        ai_message = MessagesAnalysis.response_to_aimessage_openai(
            response={"choices": [{"message": message}]}
        )
        yield StreamEvent(type="done", message=ai_message)

    def _stream_anthropic(
        self, messages: list[BaseMessage], max_tokens: int
    ) -> Iterator[StreamEvent]:
        """Anthropic 流式：按 content_block 事件状态机累积文本与 tool_use 输入。

        tool_use 的完整入参不在 ``content_block_start`` 中，需累积
        ``input_json_delta.partial_json`` 后解析（无参工具无 delta，兜底为 ``{}``）。
        """
        payload = [m.to_anthropic() for m in messages]
        try:
            stream = self.client.messages.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                stream=True,
                **self._build_anthropic_kwargs(max_tokens),
            )
        except Exception as e:
            raise RuntimeError(
                f"Anthropic 调用失败 (model={self.model}): {e}"
            ) from e

        # index -> 累积态：{"type": block 类型, 其余字段随类型累积}
        blocks: dict[int, dict] = {}

        try:
            for event in stream:
                etype = getattr(event, "type", "")
                if etype == "content_block_start":
                    index = event.index
                    block = event.content_block
                    btype = getattr(block, "type", "")
                    if btype == "tool_use":
                        blocks[index] = {
                            "type": "tool_use",
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "json": "",
                        }
                    elif btype == "thinking":
                        blocks[index] = {"type": "thinking", "thinking": "", "signature": ""}
                    else:
                        blocks[index] = {"type": "text", "text": ""}

                elif etype == "content_block_delta":
                    index = event.index
                    delta = event.delta
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta":
                        piece = getattr(delta, "text", "") or ""
                        blocks.setdefault(index, {"type": "text", "text": ""})
                        if "text" in blocks[index]:
                            blocks[index]["text"] += piece
                        if piece:
                            yield StreamEvent(type="text", text=piece)
                    elif dtype == "thinking_delta":
                        piece = getattr(delta, "thinking", "") or ""
                        buf = blocks.setdefault(
                            index, {"type": "thinking", "thinking": "", "signature": ""}
                        )
                        buf["thinking"] = buf.get("thinking", "") + piece
                        if piece:
                            yield StreamEvent(type="thinking", text=piece)
                    elif dtype == "signature_delta":
                        # thinking 块重发时需带签名，随流累积
                        buf = blocks.setdefault(
                            index, {"type": "thinking", "thinking": "", "signature": ""}
                        )
                        buf["signature"] = buf.get("signature", "") + (
                            getattr(delta, "signature", "") or ""
                        )
                    elif dtype == "input_json_delta":
                        buf = blocks.setdefault(
                            index, {"type": "tool_use", "id": "", "name": "", "json": ""}
                        )
                        piece = getattr(delta, "partial_json", "") or ""
                        buf["json"] = buf.get("json", "") + piece
                        if piece:
                            yield StreamEvent(
                                type="tool_call_delta",
                                index=index,
                                id=buf.get("id", ""),
                                name=buf.get("name", ""),
                                args_delta=piece,
                            )
                # content_block_stop / message_delta / message_stop 无需额外处理
        except Exception as e:
            raise RuntimeError(
                f"Anthropic 流式调用失败 (model={self.model}): {e}"
            ) from e

        # 复用非流式解析器：按 index 还原等价的 block 列表响应 dict
        content_blocks: list[dict] = []
        for index in sorted(blocks):
            buf = blocks[index]
            btype = buf.get("type")
            if btype == "tool_use":
                raw = (buf.get("json") or "").strip()
                try:
                    args = json.loads(raw) if raw else {}  # 无参工具无 delta，兜底为 {}
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": buf.get("id", ""),
                    "name": buf.get("name", ""),
                    "input": args,
                })
            elif btype == "thinking":
                block = {"type": "thinking", "thinking": buf.get("thinking", "")}
                if buf.get("signature"):
                    block["signature"] = buf["signature"]
                content_blocks.append(block)
            else:
                content_blocks.append({"type": "text", "text": buf.get("text", "")})

        ai_message = MessagesAnalysis.response_to_aimessage_anthropic(
            {"role": "assistant", "content": content_blocks}
        )
        yield StreamEvent(type="done", message=ai_message)
