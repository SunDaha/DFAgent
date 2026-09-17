"""MCP 发现机：扫描配置文件，把每个启用的 MCP 服务装载为 MCPClient 并存入队列。

MCP 配置唯一来源：项目根 .mcp.json 的 "mcpServers" 段（Claude Code 标准位置）。
查询时若该文件不存在，会自动创建空模板 {"mcpServers": {}}。

用法：
    discovery = MCPDiscovery()
    discovery.discover()
    client = discovery.get(timeout=1)
    print(client.call_tool("echo", {"text": "hi"}))
    discovery.close()
"""

from __future__ import annotations

import json
import os
import queue
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from dfagent.config.runtime_properties import WORKDIR
from dfagent.mcp.mcp_client import MCPClient
from dfagent.tools.tool_model import ToolInfo

# 配置里出现的连接类型别名
_STDIO_TYPES = {"local", "stdio", "command"}
_HTTP_TYPES = {"remote", "http", "streamable-http", "streamablehttp", "streamable_http"}
_UNSUPPORTED_TYPES = {"sse"}

# 配置文件里可能出现的服务段名
_SERVER_KEYS = ("mcp", "mcpServers", "servers")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ---------------------------------------------------------------- JSONC 解析


def strip_json_comments(text: str) -> str:
    """去掉 JSON 中的 // 与 /* */ 注释和尾随逗号（字符串内的内容原样保留）。"""
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    while i < length:
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < length:
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = length if end == -1 else end + 2
            continue
        out.append(char)
        i += 1
    # 去掉 } 或 ] 前的尾随逗号
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path: Path) -> dict:
    """读取 JSONC 文件为 dict。文件不存在或格式错误时返回空 dict。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(strip_json_comments(text))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- 服务配置


def _expand_env(value: Any) -> Any:
    """展开字符串里的 ${VAR}；变量不存在时替换为空串。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _normalize_headers(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    # Claude Code 的 .mcp.json 也允许 headers 写成 [{name, value}]
    if isinstance(raw, list):
        headers: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and "name" in item:
                headers[str(item["name"])] = str(item.get("value", ""))
        return headers
    return {}


@dataclass
class MCPServerSpec:
    """一个 MCP 服务端的配置快照。"""

    name: str
    transport: str  # "stdio" 或 "http"
    source: str  # 来源配置文件路径
    enabled: bool = True
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None  # 非空表示该配置无法装载

    @classmethod
    def from_dict(cls, name: str, raw: Any, source: Path) -> "MCPServerSpec":
        """把配置项（local/remote 两种写法）解析为 spec。"""
        if not isinstance(raw, dict):
            return cls(
                name=name,
                transport="stdio",
                source=str(source),
                enabled=False,
                error=f"MCP 服务 {name!r} 的配置不是对象",
            )

        raw = _expand_env(raw)
        kind = str(raw.get("type") or raw.get("transport") or "").strip().lower()
        enabled = bool(raw.get("enabled", raw.get("disabled") is not True))

        if kind in _STDIO_TYPES:
            transport = "stdio"
        elif kind in _HTTP_TYPES:
            transport = "http"
        elif kind in _UNSUPPORTED_TYPES:
            return cls(
                name=name,
                transport=kind,
                source=str(source),
                enabled=False,
                error=f"MCP 服务 {name!r} 使用暂不支持的连接类型 {kind!r}",
            )
        elif raw.get("url"):
            transport = "http"
        elif raw.get("command"):
            transport = "stdio"
        else:
            return cls(
                name=name,
                transport="unknown",
                source=str(source),
                enabled=False,
                error=f"MCP 服务 {name!r} 缺少 command 或 url",
            )

        command = raw.get("command") or []
        if isinstance(command, str):
            command = command.split()
        command = [str(part) for part in command]
        args = raw.get("args") or []
        if isinstance(args, str):
            args = args.split()
        args = [str(part) for part in args]

        return cls(
            name=name,
            transport=transport,
            source=str(source),
            enabled=enabled,
            command=command,
            args=args,
            env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
            cwd=raw.get("cwd"),
            url=raw.get("url"),
            headers=_normalize_headers(raw.get("headers")),
        )

    def to_client(self, *, connect_timeout: float = 30.0, call_timeout: float = 60.0) -> MCPClient:
        """按本配置创建一个未连接的 MCPClient。"""
        return MCPClient(
            self.name,
            self.transport,
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
            url=self.url,
            headers=self.headers,
            connect_timeout=connect_timeout,
            call_timeout=call_timeout,
        )


def default_config_paths() -> list[Path]:
    """MCP 配置唯一来源：项目根 .mcp.json。"""
    return [WORKDIR / ".mcp.json"]


def ensure_mcp_config(path: Path | None = None) -> Path:
    """确保 MCP 配置文件存在，缺失则创建空模板 {"mcpServers": {}}。返回文件路径。"""
    target = Path(path) if path is not None else default_config_paths()[0]
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"mcpServers": {}}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return target


def _iter_server_items(data: dict) -> Iterable[tuple[str, Any]]:
    for key in _SERVER_KEYS:
        section = data.get(key)
        if isinstance(section, dict):
            for name, raw in section.items():
                yield str(name), raw


def discover_specs(paths: Iterable[Path] | None = None) -> list[MCPServerSpec]:
    """扫描配置文件，按发现顺序返回去重后的服务配置。

    未显式指定 paths 时，使用默认来源 .mcp.json，缺失则先自动创建空模板。
    """
    if paths is None:
        ensure_mcp_config()
        paths = default_config_paths()
    specs: list[MCPServerSpec] = []
    seen: set[str] = set()
    for path in (Path(p) for p in paths):
        for name, raw in _iter_server_items(load_jsonc(path)):
            if name in seen:
                continue
            seen.add(name)
            specs.append(MCPServerSpec.from_dict(name, raw, path))
    return specs




# ---------------------------------------------------------------- 发现机


class MCPDiscovery:
    """发现 MCP 服务，装载成 MCPClient，并存入队列。"""

    def __init__(
        self,
        paths: Iterable[Path] | None = None,
        *,
        connect_timeout: float = 30.0,
        call_timeout: float = 60.0,
        list_tools_on_connect: bool = True,
    ) -> None:
        self.paths = [Path(p) for p in (paths if paths is not None else default_config_paths())]
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.list_tools_on_connect = list_tools_on_connect

        self.queue: queue.Queue[MCPClient] = queue.Queue()
        self.clients: dict[str, MCPClient] = {}
        self.errors: list[str] = []

    # ------------------------------------------------------------ 发现

    def discover(self) -> queue.Queue[MCPClient]:
        """扫描配置、连接服务、拉取工具列表，成功的客户端入队。返回队列本身。"""
        # 查询前确保配置文件存在（缺失自动建空模板），再逐个装载
        for path in self.paths:
            ensure_mcp_config(path)
        for spec in discover_specs(self.paths):
            self.load(spec)
        return self.queue

    def load(self, spec: MCPServerSpec) -> MCPClient | None:
        """装载单个服务配置：连接并拉取工具列表，失败则记录错误并返回 None。"""
        if not spec.enabled:
            return None
        if spec.error:
            self._record_error(spec.error)
            return None
        if spec.name in self.clients:
            self._record_error(f"MCP 服务 {spec.name!r} 已装载，跳过重复项")
            return None
        if spec.transport not in ("stdio", "http"):
            self._record_error(spec.error or f"MCP 服务 {spec.name!r} 连接类型无效")
            return None

        client = spec.to_client(
            connect_timeout=self.connect_timeout, call_timeout=self.call_timeout
        )
        try:
            client.connect()
            if self.list_tools_on_connect:
                client.list_tools()
        except Exception as error:  # noqa: BLE001 - 单个服务失败不影响其他服务
            client.close()
            source = Path(spec.source).name
            self._record_error(f"MCP 服务 {spec.name!r}（{source}）装载失败: {error}")
            return None

        self.clients[spec.name] = client
        self.queue.put(client)
        return client

    def _record_error(self, message: str) -> None:
        self.errors.append(message)

    # ------------------------------------------------------------ 队列访问

    def get(self, timeout: float | None = None) -> MCPClient | None:
        """从队列取一个已装载的客户端；超时返回 None。"""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list[MCPClient]:
        """取空队列，返回全部剩余客户端。"""
        clients: list[MCPClient] = []
        while True:
            try:
                clients.append(self.queue.get_nowait())
            except queue.Empty:
                return clients

    def get_client(self, name: str) -> MCPClient | None:
        return self.clients.get(name)

    def list_tools(self) -> dict[str, list[dict]]:
        """返回当前发现结果的工具快照。

        实现放在 ``mcp_handler``，这里通过局部导入提供面向对象的兼容入口，
        避免模块初始化时形成循环依赖。
        """
        from dfagent.mcp.mcp_handler import list_tools

        return list_tools(self)

    def to_tool_infos(self, return_direct: bool = True) -> list[ToolInfo]:
        """把当前发现的全部工具转换为 ``ToolInfo`` 列表。"""
        from dfagent.mcp.mcp_handler import to_tool_infos

        return to_tool_infos(self, return_direct)

    def close(self) -> None:
        """关闭全部已装载的客户端。"""
        for client in self.clients.values():
            client.close()
        self.clients.clear()
        self.drain()

    def __enter__(self) -> "MCPDiscovery":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
