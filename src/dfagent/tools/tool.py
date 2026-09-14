import re
import types
import typing
import inspect
from typing import Callable,Any, get_origin, get_args, get_type_hints, Literal
from pydantic import BaseModel, ConfigDict, Field as PydanticField, create_model, ValidationError
from dfagent.tools.tool_model import ToolInfo
from dfagent.app_state_store import TOOL_REGISTRY

# 作用: 获取参数类型
_TYPE_MAP: dict[type, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    dict:  "object",
    list:  "array",
}
def _py_type_to_json_type(py_type:type):
    origin = get_origin(py_type)
    if origin:
        if origin is typing.Annotated:
            args = get_args(py_type)
            return _py_type_to_json_type(args[0])
        if origin in (typing.Union,types.UnionType):
            args = get_args(py_type)
            non_none = [n for n in args if n is not type(None)]
            if len(non_none) == 1:
                return _py_type_to_json_type(non_none[0])
        if origin is list:
            return _TYPE_MAP.get(list,"array")
    return _TYPE_MAP.get(py_type,"string")

def _is_optional(py_type: type) -> bool:
    """判断类型是否为 Optional（Union[X, None] / X | None）。"""
    origin = get_origin(py_type)
    # Annotated[Optional[X], ...] → 先解包 Annotated
    if origin is typing.Annotated:
        args = get_args(py_type)
        return _is_optional(args[0])
    if origin in (typing.Union, types.UnionType):
        args = get_args(py_type)
        return type(None) in args
    return False


# 作用: 获取参数 items 的内容
def Field(
    description: str = "",
    *,
    min_length: int | None = None,
    max_length: int | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    enum: list | None = None,
    json_schema: dict | None = None,
) -> dict:
    """参数元数据描述符，通过 Annotated[type, Field(...)] 定义每个参数的描述和约束。

    Usage:
        path: Annotated[str, Field(description="文件路径")]
        limit: Annotated[int | None, Field(description="最大行数", minimum=1)] = None
        todos: Annotated[list, Field(
            description="任务列表",
            json_schema={"items": {"type": "object", "properties": {...}}}
        )]
    """
    meta: dict[str, Any] = {"description": description}
    if min_length is not None:
        meta["minLength"] = min_length
    if max_length is not None:
        meta["maxLength"] = max_length
    if minimum is not None:
        meta["minimum"] = minimum
    if maximum is not None:
        meta["maximum"] = maximum
    if enum is not None:
        meta["enum"] = enum
    if json_schema is not None:
        meta["json_schema"] = json_schema
    return meta


def _get_field_meta(param: inspect.Parameter) -> dict | None:
    """从 Annotated 类型中提取 Field 元数据。"""
    ann = param.annotation
    if ann is inspect.Parameter.empty:
        return None
    origin = get_origin(ann)
    if origin is not typing.Annotated:
        return None
    args = get_args(ann)
    for arg in args[1:]:  # 跳过基础类型，只看 metadata
        if isinstance(arg, dict):
            return arg
    return None

def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict，override 中的值覆盖 base。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def create_schema_from_function(func: Callable) -> type[BaseModel]:
    """根据函数签名动态创建用于校验工具参数的 Pydantic Model。"""
    try:
        type_hints = get_type_hints(func, include_extras=True)
    except (NameError, TypeError):
        type_hints = getattr(func, "__annotations__", {})

    fields: dict[str, tuple[Any, Any]] = {}
    signature = inspect.signature(func)
    for param_name, param in signature.parameters.items():
        if param_name in {"self", "cls"} or param.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue

        annotation = type_hints.get(param_name, Any)
        metadata = _get_field_meta(param) or {}
        metadata = dict(metadata)
        description = metadata.pop("description", None)
        json_schema = metadata.pop("json_schema", None)

        enum_values = metadata.pop("enum", None)
        if enum_values is not None:
            annotation = Literal[tuple(enum_values)]

        pydantic_constraints = {
            "min_length": metadata.pop("minLength")
            if "minLength" in metadata else None,
            "max_length": metadata.pop("maxLength")
            if "maxLength" in metadata else None,
            "ge": metadata.pop("minimum") if "minimum" in metadata else None,
            "le": metadata.pop("maximum") if "maximum" in metadata else None,
        }
        field_kwargs = {
            key: value
            for key, value in pydantic_constraints.items()
            if value is not None
        }
        if description:
            field_kwargs["description"] = description
        extras: dict[str, Any] = {}
        if isinstance(json_schema, dict):
            extras.update(json_schema)
        extras.update(metadata)
        if extras:
            field_kwargs["json_schema_extra"] = extras

        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[param_name] = (annotation, PydanticField(default, **field_kwargs))

    model_name = f"{getattr(func, '__name__', 'tool').title()}Args"
    return create_model(
        model_name,
        __base__=BaseModel,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )




# 作用: 获取参数的描述
def _parse_agrs_from_doc(doc:str)->dict[str,str]:
    if not doc:
        return {}
    pattern = r"^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$"
    in_args = False
    result: dict[str, str] = {}
    for line in doc.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("args:") or lower.startswith("arguments:"):
            in_args = True
            continue
        if in_args:
            if not stripped or lower.startswith(("returns:", "raises:", "yields:", "examples:")):
                break
            m = re.match(pattern, stripped)
            if m:
                result[m.group(1)] = m.group(2).strip()
    return result



# 作用: 将工具元信息转换为openai或anthropicAPI的tool定义
def convert_openai_tool(
    name: str,
    description: str,
    properties: dict[str, dict],
    required: list[str],
) -> dict:
    """将工具元信息转换为 OpenAI function tool 定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def convert_anthropic_tool(
    name: str,
    description: str,
    properties: dict[str, dict],
    required: list[str],
) -> dict:
    """将工具元信息转换为 Anthropic tool 定义。"""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }



def tool(
    func: Callable | None = None,
    name: str | None = None,
    description: str | None = None,
    return_direct:bool = True,
):
    """工具封装注解

    Args:
        func (Callable | None, optional): 函数. Defaults to None.
        name (str | None, optional): 工具名称. Defaults to None.
        description (str | None, optional): 工具描述. Defaults to None.
        return_direct (bool, optional): 工具结果是否直接返回用户，不再经过模型二次处理. Defaults to True.
    """
    def decorator(f:Callable)->Callable:
        tool_name:str = ""
        tool_desc:str = ""
        properties: dict[str, dict] = {}
        required: list[str] = []
        
        # 提取工具名
        tool_name = name or f.__name__
        
        # 提取工具描述
        if description:
            tool_desc = description
        elif f.__doc__:
            tool_desc = f.__doc__.strip().splitlines()[0]
        else:
            tool_desc = f"No description for {tool_name}"
        
        
        
        # 提取函数签名
        sig = inspect.signature(f)
        
        # 解析参数
        # 1.从doc中解析参数描述
        args_desc_from_doc = None
        if f.__doc__:
            args_desc_from_doc = _parse_agrs_from_doc(f.__doc__)
        
        # 2.解析参数类型和描述
        for param_name,param in sig.parameters.items():
            if param_name in ("self","cls"):
                continue
            json_type = "string"
            has_default = param.default is not inspect.Parameter.empty
            optional = False
            if param.annotation is not inspect.Parameter.empty:
                json_type = _py_type_to_json_type(param.annotation)
                optional = _is_optional(param.annotation)
            
            field_meta = _get_field_meta(param)
            if field_meta:
                field_meta = dict(field_meta)
            if field_meta:
                param_desc = field_meta.pop("description", f"参数 {param_name}")
            elif args_desc_from_doc and param_name in args_desc_from_doc:
                param_desc = args_desc_from_doc.get(param_name)
            else:
                param_desc = None
                
            field_def: dict[str, Any] = {"type": json_type, "description": param_desc}
            # 合并 Field 中除 description/json_schema 外的约束（minLength, minimum, enum 等）
            if field_meta:
                field_def.update(
                    {
                        key: value
                        for key, value in field_meta.items()
                        if key not in {"description", "json_schema"}
                    }
                )
                json_schema = field_meta.get("json_schema")
                if isinstance(json_schema, dict):
                    field_def = _deep_merge(field_def, json_schema)
            properties[param_name] = field_def
            if not has_default and not optional:
                required.append(param_name)
        
        # 动态生成 Pydantic Model
        args_schema = create_schema_from_function(f)
        
        
        
        # 工具信息定义转换openai和anthropic格式
        openai_def = convert_openai_tool(tool_name,tool_desc,properties,required)
        anthropic_def = convert_anthropic_tool(tool_name,tool_desc,properties,required)
        
        
        # 注册工具
        TOOL_REGISTRY[tool_name] = ToolInfo(
            name=tool_name,
            description=tool_desc,
            function=f,
            openai_def=openai_def,
            anthropic_def=anthropic_def,
            return_direct=return_direct,
            args_schema=args_schema,
        )
        return f
        
    if func is not None:
        return decorator(func)
    return decorator








