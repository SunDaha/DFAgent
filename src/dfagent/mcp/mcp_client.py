"""MCP 客户端：把官方 mcp SDK 的 async 会话同步化，供同步的 Agent 循环调用。

三种模式：
    - "stdio"      本地服务，以子进程方式启动（对应 config 里的 local）
    - "http"       远端服务，走 streamable HTTP（对应 config 里的 remote）
    - "in-process" 不连真实服务，使用 register() 注册的进程内桩，供测试使用
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import threading
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Callable

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    get_default_environment,
    stdio_client,
)
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


class MCPError(RuntimeError):
    """MCP 客户端错误基类。"""


class MCPConnectError(MCPError):
    """连接或初始化 MCP 服务失败。"""


class MCPTimeoutError(MCPError):
    """等待 MCP 服务响应超时。"""


class MCPNotConnectedError(MCPError):
    """在未连接（或连接已断开）的客户端上发起请求。"""


# ---------------------------------------------------------------- 后台事件循环


class _LoopThread:
    """常驻后台事件循环，把 SDK 的 async 会话暴露给同步调用方。

    SDK 的会话必须在其所属事件循环内使用，因此所有会话都由本循环中的
    常驻任务持有，同步代码只做请求投递与结果等待。
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="mcp-event-loop", daemon=True
        )
        self._thread.start()
        atexit.register(self.shutdown)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def spawn(self, coro) -> concurrent.futures.Future:
        """在后台循环中启动一个常驻协程，返回可等待的 Future。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def shutdown(self) -> None:
        if self._loop.is_closed() or not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)


_LOOP = _LoopThread()


# ---------------------------------------------------------------- 结果转换


def _tool_to_dict(tool: Any) -> dict:
    """把 SDK 的 Tool 对象转成本项目使用的普通 dict。"""
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "input_schema": getattr(tool, "input_schema", None)
        or {"type": "object", "properties": {}},
    }


def _result_to_text(result: Any) -> str:
    """把 SDK 的 CallToolResult 转成文本，保持 call_tool 返回字符串的约定。"""
    prefix = "MCP error: " if getattr(result, "is_error", False) else ""
    chunks: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            chunks.append(str(text))
        else:
            chunks.append(str(block))
    if not chunks and getattr(result, "structured_content", None) is not None:
        chunks.append(str(result.structured_content))
    if not chunks and getattr(result, "result_type", None) not in (None, "complete"):
        chunks.append(f"[{result.result_type} result]")
    return prefix + ("\n".join(chunks) if chunks else "(no output)")


# ---------------------------------------------------------------- 客户端


class MCPClient:
    """一个 MCP 服务端的同步客户端。

    真实连接（stdio / http）由后台事件循环中的常驻会话任务持有，
    请求串行投递给该任务执行；断开或超时后不再复用会话。
    """

    def __init__(
        self,
        name: str,
        mode: str = "in-process",
        *,
        command: list[str] | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        connect_timeout: float = 30.0,
        call_timeout: float = 60.0,
    ) -> None:
        if mode not in ("stdio", "http", "in-process"):
            raise ValueError(f"不支持的 MCP 连接模式: {mode!r}")
        self.name = name
        self.mode = mode
        self.command = list(command or [])
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.url = url
        self.headers = dict(headers or {})
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout

        # 已发现的工具（统一 dict：name / description / input_schema）
        self.tools: list[dict] = []
        # in-process 模式使用：工具定义 -> 处理函数
        self.handlers: dict[str, Callable] = {}

        self._session: ClientSession | None = None
        self._requests: asyncio.Queue | None = None
        self._serve_future: concurrent.futures.Future | None = None
        self._ready = threading.Event()
        self._connected = False
        self._error: BaseException | None = None

    # ------------------------------------------------------------ 进程内桩

    def register(self, tool_defs: list[dict], handlers: dict[str, Callable]) -> None:
        """注册进程内工具（仅 in-process 模式使用）。"""
        names = [tool["name"] for tool in tool_defs]
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("Every MCP tool needs a non-empty name")
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate MCP tool name on server {self.name!r}")
        missing = [name for name in names if name not in handlers]
        if missing:
            raise ValueError(f"Missing MCP handlers: {', '.join(missing)}")
        self.handlers = handlers
        self.tools = [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema")
                or tool.get("inputSchema")
                or {"type": "object", "properties": {}},
            }
            for tool in tool_defs
        ]

    def _call_in_process(self, tool_name: str, args: dict) -> str:
        handler = self.handlers.get(tool_name)
        if handler is None:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return str(handler(**args))
        except Exception as error:  # noqa: BLE001 - 错误以文本回传给模型
            return f"MCP error: {type(error).__name__}: {error}"

    # ------------------------------------------------------------ 连接生命周期

    def connect(self) -> "MCPClient":
        """建立连接并完成 MCP initialize。失败抛 MCPConnectError / MCPTimeoutError。"""
        if self._connected:
            return self
        if self.mode == "in-process":
            self._connected = True
            return self

        self._error = None
        self._ready.clear()
        self._requests = asyncio.Queue()
        self._serve_future = _LOOP.spawn(self._serve())
        # 会话任务在完成 initialize（或失败）后唤醒这里
        if not self._ready.wait(self.connect_timeout):
            self._error = MCPTimeoutError(
                f"MCP 服务 {self.name!r} 连接超时（{self.connect_timeout}s）"
            )
        if not self._connected:
            error = self._error or MCPConnectError(f"MCP 服务 {self.name!r} 连接失败")
            self._teardown()
            raise error
        return self

    @asynccontextmanager
    async def _open_transport(self):
        """按模式打开底层传输，产出 (read, write) 流。"""
        if self.mode == "stdio":
            if not self.command:
                raise MCPConnectError(f"MCP 服务 {self.name!r} 缺少 command")
            params = StdioServerParameters(
                command=self.command[0],
                args=[*self.command[1:], *self.args],
                # 保留 SDK 默认环境（PATH/HOME 等），再叠加用户配置的变量
                env={**get_default_environment(), **self.env},
                cwd=self.cwd,
            )
            async with stdio_client(params) as (read, write):
                yield read, write
        else:
            if not self.url:
                raise MCPConnectError(f"MCP 服务 {self.name!r} 缺少 url")
            http_client = create_mcp_http_client(headers=self.headers or None)
            async with streamable_http_client(
                self.url, http_client=http_client
            ) as (read, write):
                yield read, write

    async def _serve(self) -> None:
        """常驻会话任务：持有连接，串行处理请求，直到收到关闭信号。"""
        try:
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(self._open_transport())
                session = await stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=self.call_timeout)
                )
                await session.initialize()
                self._session = session
                self._connected = True
                self._ready.set()

                while True:
                    request = await self._requests.get()
                    if request is None:
                        break
                    kind, payload, future = request
                    if future.set_running_or_notify_cancel() is False:
                        continue
                    try:
                        result = await asyncio.wait_for(
                            self._dispatch(session, kind, payload), self.call_timeout
                        )
                    except asyncio.TimeoutError:
                        timeout_error = MCPTimeoutError(
                            f"MCP 服务 {self.name!r} 响应超时（{self.call_timeout}s）"
                        )
                        future.set_exception(timeout_error)
                        # 超时后无法确定会话状态，直接断开，避免后续请求错位
                        self._error = timeout_error
                        break
                    except Exception as error:  # noqa: BLE001 - 交给调用方判断
                        future.set_exception(error)
                    else:
                        future.set_result(result)
        except Exception as error:  # noqa: BLE001 - 连接期错误记录下来供 connect 抛出
            self._error = error
        finally:
            self._connected = False
            self._session = None
            self._ready.set()
            self._fail_pending(MCPNotConnectedError(f"MCP 服务 {self.name!r} 已断开"))

    async def _dispatch(self, session: ClientSession, kind: str, payload: Any) -> Any:
        if kind == "list_tools":
            result = await session.list_tools()
            return [_tool_to_dict(tool) for tool in result.tools]
        if kind == "call_tool":
            tool_name, args = payload
            result = await session.call_tool(tool_name, args)
            return _result_to_text(result)
        raise MCPError(f"未知的 MCP 请求类型: {kind!r}")

    def _fail_pending(self, error: BaseException) -> None:
        """会话结束时，把仍在排队的请求标记为失败，避免调用方永久阻塞。"""
        requests = self._requests
        if requests is None:
            return
        while not requests.empty():
            try:
                item = requests.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 竞态兜底
                break
            if item is None:
                continue
            _, _, future = item
            if future.set_running_or_notify_cancel():
                future.set_exception(error)

    def _teardown(self) -> None:
        self._connected = False
        self._session = None
        # 先投递关闭信号，再取消：若会话任务还在连接中，连上后会自行退出
        if self._requests is not None:
            try:
                _LOOP.loop.call_soon_threadsafe(self._requests.put_nowait, None)
            except RuntimeError:  # 事件循环已关闭
                pass
        if self._serve_future is not None:
            self._serve_future.cancel()

    def close(self, timeout: float = 5.0) -> None:
        """关闭会话并回收子进程/HTTP 连接。可重复调用。"""
        if self.mode == "in-process":
            self._connected = False
            return
        future = self._serve_future
        if future is None:
            return
        requests = self._requests
        if requests is not None and self._connected:
            _LOOP.loop.call_soon_threadsafe(requests.put_nowait, None)
            try:
                future.result(timeout)
            except Exception:  # noqa: BLE001 - 关闭失败不影响后续清理
                future.cancel()
        self._teardown()
        self._serve_future = None
        self._requests = None

    def __enter__(self) -> "MCPClient":
        return self.connect()

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------ 同步 API

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def connect_error(self) -> BaseException | None:
        return self._error

    def _request(self, kind: str, payload: Any, timeout: float | None = None) -> Any:
        if self.mode == "in-process":
            raise MCPNotConnectedError(f"MCP 服务 {self.name!r} 是进程内桩，不支持请求")
        if not self._connected or self._requests is None:
            detail = f": {self._error}" if self._error else ""
            raise MCPConnectError(f"MCP 服务 {self.name!r} 未连接{detail}")

        future: concurrent.futures.Future = concurrent.futures.Future()
        _LOOP.loop.call_soon_threadsafe(self._requests.put_nowait, (kind, payload, future))
        try:
            return future.result((timeout or self.call_timeout) + 5)
        except concurrent.futures.TimeoutError as error:
            raise MCPTimeoutError(
                f"MCP 服务 {self.name!r} 请求 {kind} 超时"
            ) from error

    def list_tools(self, timeout: float | None = None) -> list[dict]:
        """拉取工具列表并缓存到 self.tools。进程内桩直接返回已注册的工具。"""
        if self.mode == "in-process":
            return self.tools
        self.tools = self._request("list_tools", None, timeout)
        return self.tools

    def call_tool(self, tool_name: str, args: dict) -> str:
        """调用工具，始终返回字符串：失败以 "MCP error: ..." 文本回传。"""
        if self.mode == "in-process":
            return self._call_in_process(tool_name, args)
        try:
            return self._request("call_tool", (tool_name, args))
        except MCPError as error:
            return f"MCP error: {error}"
        except Exception as error:  # noqa: BLE001 - 错误以文本回传给模型
            return f"MCP error: {type(error).__name__}: {error}"
