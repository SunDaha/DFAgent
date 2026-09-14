from dataclasses import dataclass
from pydantic import BaseModel, ValidationError
from typing import Callable, Any

@dataclass
class ToolInfo:
    """单个工具的完整元信息。"""
    name: str                 # Tool Name
    description: str          # Tool description
    function: Callable        # Tool Function
    openai_def: dict          # OpenAI function calling 的 tool 定义
    anthropic_def: dict       # Anthropic function calling 的 tool 定义
    return_direct:bool        # 是否直接返回结果, 不在进行模型二次处理
    args_schema: type[BaseModel] | None = None  # 工具参数校验模型
    
    def get_openai_def(self):
        return self.openai_def
    
    def get_anthropic_def(self):
        return self.anthropic_def
    
    def get_args_schema(self):
        return self.args_schema

    def execute(self, param: dict) -> tuple[bool, Any]:
        """校验参数后执行工具函数。

        返回:
            (True, 工具返回值)        校验通过且执行成功
            (False, 报错信息字符串)    校验失败或执行异常
        """
        if self.args_schema is not None:
            try:
                instance = self.args_schema(**param)
            except ValidationError as e:
                return False, _format_validation_error(e)
            param = instance.model_dump()
        try:
            return True, self.function(**param)
        except Exception as e:  # noqa: BLE001
            return False, f"工具执行异常 [{type(e).__name__}]: {e}"




def _format_validation_error(e: ValidationError) -> str:
    """将 pydantic ValidationError 转为可读的报错信息。"""
    lines = [f"参数校验失败（共 {e.error_count()} 处）："]
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "<root>"
        lines.append(f"  - 参数 {loc}: {err['msg']}")
    return "\n".join(lines)        