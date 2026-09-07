"""统一 Model：屏蔽 OpenAI / Anthropic 差异，一律返回 AIMessages。"""
from __future__ import annotations

from openai import OpenAI
from anthropic import Anthropic

from dfagent import client as _global_client, model as _global_model
from dfagent.base.messages import BaseMessage, AIMessages, MessagesAnalysis

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
                 tools:list[dict] | None = [],
                 thinking_effort:str | None = None,
                 ) -> None:
        self.client = client or _global_client
        self.model = model or _global_model
        self.tools = tools
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

    def _chat_openai(self, messages: list[BaseMessage], max_tokens: int) -> AIMessages:
        # ToolMessage.to_openai() 返回多条 role=tool 消息，需展平；直接 list 推导会产生嵌套列表
        payload = MessagesAnalysis.openai_BaseMessages_to_dict(messages)
        kwargs: dict = {}
        if self.tools:
            kwargs["tools"] = self.tools
        # 思考模式：仅当 effort 非 None 且值合法才开启 reasoning
        if self.thinking_effort is not None:
            if self.thinking_effort in _REASONING_EFFORT_ALLOWED:
                kwargs["reasoning_effort"] = self.thinking_effort
            else:
                print(f"[WARN] 无效 reasoning_effort: {self.thinking_effort}，已忽略")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                **kwargs,
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
        try:
            response = self.client.messages.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as e:
            raise RuntimeError(
                f"Anthropic 调用失败 (model={self.model}): {e}"
            ) from e
        # Anthropic SDK 返回 pydantic Message，先 model_dump 成 dict 再解析
        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        return MessagesAnalysis.response_to_aimessage_anthropic(data)
