# DFAgent

一个从零实现的 ReAct Agent 框架：统一消息抽象、声明式工具注册、MCP 动态工具加载、分层上下文压缩、文件式长期记忆。

面向 **Python 3.12+**，同时支持 OpenAI 与 Anthropic 两种模型后端。

---

## 特性

| 能力 | 说明 |
| --- | --- |
| **统一模型封装** | `Model` 屏蔽 OpenAI / Anthropic 差异，输入 `list[BaseMessage]`，输出统一 `AIMessages` |
| **声明式工具** | `@tool` 装饰器从函数签名 + docstring + `Field()` 元数据自动生成 JSON Schema 与 Pydantic 校验模型 |
| **MCP 动态工具** | 从 `.mcp.json` 发现 MCP 服务，`search_tool` 搜索、`load_tool` 按需加载，避免一次性塞满工具列表 |
| **分层上下文压缩** | 四级策略：结果持久化 → 中间截断 → 结果占位 → LLM 摘要 |
| **长期记忆** | 对话结束后自动抽取持久记忆落盘，下次会话按相关性召回 |
| **Hook 机制** | 6 类事件钩子（权限检查、日志、大输出截断、调试打印…） |
| **后台任务** | bash 工具支持 `run_in_background`，结果在后续轮次自动注入 |
| **Skills** | 扫描 `skills/*/SKILL.md`，按需 `load_skill` 加载全文 |
| **Worktree** | Git worktree 的创建 / 删除 / 校验，用于隔离的工作目录 |

---

## 快速开始

### 1. 安装

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -e .
```

### 2. 配置环境变量

在项目根目录创建 `.env`：

```dotenv
APIKEY=sk-xxxxxxxxxxxxxxxx
BASEURL=https://api.example.com/v1
MODEL=gpt-5.5
CHOICE_API=openai        # openai 或 anthropic
```

`CHOICE_API` 决定 `client_config.get_client()` 创建哪种客户端，`ReActAgent` 会按客户端类型自动选择对应的循环实现。

### 3. 最小示例

```python
from dfagent.config.client_config import client, model
from dfagent.base.Agent import ReActAgent
from dfagent.tools.tool_manager import get_tools_list
from dfagent.base.messages import HumanMessage, BaseMessage

# 1. 取全部已注册工具的 OpenAI 定义
tools = [t.get_openai_def() for t in get_tools_list()]

# 2. 构造 Agent
agent = ReActAgent(client=client, model_name=model, tools=tools)

# 3. 跑循环
messages: list[BaseMessage] = [HumanMessage(content="列出当前目录下的 Python 文件")]
print(agent.loop(messages))
```

`loop()` 是完整的 ReAct 循环：压缩上下文 → 请求模型 → 执行工具 → 追加结果 → 直到模型不再调用工具为止。

### 4. 配置 MCP 服务（可选）

复制模板并编辑 `.mcp.json`：

```bash
cp .mcp.template.json .mcp.json
```

```json
{
  "mcpServers": {
    "weather": {
      "type": "local",
      "command": ["python", "src/dfagent/test/fastmcp_server.py"],
      "enabled": true
    },
    "remote-api": {
      "type": "remote",
      "url": "https://example.com/mcp",
      "enabled": true,
      "headers": { "Authorization": "Bearer ${MY_TOKEN}" }
    }
  }
}
```

- `local` / `stdio` / `command` → 子进程 stdio 传输
- `remote` / `http` / `streamable-http` → Streamable HTTP 传输
- 配置支持 JSONC（`//` 与 `/* */` 注释、尾随逗号）和 `${ENV_VAR}` 变量展开

加载成功的 MCP 工具会在下一轮请求前自动注入模型的工具列表，无需手动刷新。

---

## 目录结构

```text
src/dfagent/
├── __init__.py              # 导出全局配置常量与 client/model
├── app_state_store.py       # 全局单例：工具注册表、MCP 发现机、Agent 名册
├── base/
│   ├── Agent.py             # Agent / ReActAgent / ReflexionAgent / PlanAndExecuteAgent
│   ├── model.py             # Model：OpenAI / Anthropic 统一对话封装
│   └── messages.py          # BaseMessage / System / Human / AI / Tool + 格式互转
├── config/
│   ├── client_config.py     # 从 .env 读取 client / model
│   └── runtime_properties.py# 运行时常量（上下文预算、重试次数、目录等）
├── context/
│   └── context_compact.py   # 四级上下文压缩
├── memory/
│   └── memory.py            # 记忆抽取、召回、合并
├── prompt/
│   └── prompt_builder.py    # 组装 System Prompt
├── hook/
│   ├── hooks.py             # HookEvent 定义 + 注册 + 触发
│   ├── pre_tool_use.py      # 权限检查、参数日志
│   ├── post_tool_use.py     # 超大输出截断
│   └── de_bug.py            # messages 可视化打印
├── tools/
│   ├── tool.py              # @tool 装饰器 + Field() 元数据 + schema 生成
│   ├── tool_model.py        # ToolInfo：执行与参数校验
│   ├── tool_manager.py      # 工具查找、批量执行、后台注入
│   ├── base_tools.py        # bash / read / write / edit / glob / grep / compact
│   ├── write_todo_tool.py   # 任务清单（含轮次提醒）
│   ├── background.py        # 后台 bash 任务管理
│   ├── context_retrieval.py # 取回被持久化的工具结果
│   ├── skills_tool.py       # load_skill
│   ├── search_tool.py       # MCP 工具搜索
│   └── load_tool.py         # MCP 工具加载
├── mcp/
│   ├── mcp_discovery.py     # 扫描配置、连接服务、拉取工具列表
│   ├── mcp_client.py        # 同步化的 MCP 客户端（后台事件循环）
│   └── mcp_handler.py       # 工具搜索 / 加载 / 执行 / 转换为 ToolInfo
├── skills/load_skills.py    # 扫描 skills/*/SKILL.md
├── utils/                   # git 命令封装、系统信息
├── worktree/                # Git worktree 管理
└── test/                    # 可执行的自测脚本
```

---

## 核心设计

### 消息抽象

所有消息继承 `BaseMessage`，并通过 `to_openai()` / `to_anthropic()` 转成各家 API 格式：

| 类 | 说明 |
| --- | --- |
| `SystemMessage` | 系统提示词 |
| `HumanMessage` | 用户消息，`content` 可为字符串或 block 列表 |
| `AIMessages` | 模型回复，携带 `tool_calls: list[ToolCall]` |
| `ToolMessage` | **一组**工具结果，`id` / `name` / `content` 三个列表一一对应 |

`MessagesAnalysis` 提供双向转换：`openai_dict_to_BaseMessages` / `anthropic_dict_to_BaseMessages` 用于反序列化，`response_to_aimessage_*` 用于解析 API 响应；连续的多条 `role="tool"` 消息会被合并成单个 `ToolMessage`。

### 工具注册

```python
from typing import Annotated
from dfagent.tools.tool import tool, Field

@tool(name="greet", description="向指定用户问好")
def run_greet(
    name: Annotated[str, Field(description="用户名字", min_length=1)],
    times: Annotated[int, Field(description="重复次数", minimum=1, maximum=10)] = 1,
) -> str:
    """Args:
        name: 用户名字
        times: 重复次数
    """
    return f"Hello {name}! " * times
```

装饰器在导入时完成：

1. 从函数签名推导 JSON 类型与必填项（`Optional[X]` 视为非必填）
2. 从 `Field()` 元数据提取描述与约束（`minLength` / `minimum` / `enum` / 自定义 `json_schema`）
3. 缺省时回退解析 docstring 的 `Args:` 段
4. 动态生成 Pydantic 模型（`extra="forbid"`）用于执行前校验
5. 生成 OpenAI 与 Anthropic 两套 tool 定义，注册进 `TOOL_REGISTRY`

`ToolInfo.execute()` 统一返回 `(success, result)`，参数校验失败或执行异常都会被转成文本回传给模型，不会中断循环。

### 上下文压缩

`_loop_openai` 每轮请求前依次执行四层压缩（顺序即优先级）：

| 层 | 函数 | 策略 |
| --- | --- | --- |
| 1 | `tool_result_budget` | 末尾 `ToolMessage` 总量超 200000 字符时，把超阈值条目写入 `.task_outputs/tool-results/`，原位置换成占位符 |
| 2 | `snip_compact` | 消息数 > 50 时保留前 3 条与尾部，中间替换为 `[snipped N messages]`（自动对齐 assistant↔tool 配对） |
| 3 | `micro_compact` | 保留最近 20 条工具结果，更早的若非 `read` 则替换为占位符 |
| 4 | `compact_history` | 仅在 API 报 `prompt_too_long` 时触发：保留 system + 首条 user + 最近 3 轮，中间用 LLM 结构化摘要替代 |

第 4 层的摘要刻意保留「失败尝试」与「用户约束」两节，避免压缩后重蹈覆辙。完整历史会先写入 `.transcripts/`。

被持久化的结果可由 `retrieve_tool_result(file_name)` 取回，因此占位符不是信息丢弃。

### 长期记忆

记忆存放在 `~/DFAgent/project/{用户名}-{工作目录名}/memory/`，每条记忆一个带 YAML frontmatter 的 Markdown 文件，`MEMORY.md` 为索引。

- **抽取**：每轮对话结束（模型不再调用工具）时，由 LLM 判断哪些内容属于持久知识，分 `user` / `feedback` / `project` / `reference` 四类落盘
- **过滤**：临时性标记（"本次会话"、"暂时" 等）与重复内容不入库
- **召回**：每轮构建 System Prompt 时，用最近 3 条用户消息检索相关记忆注入
- **合并**：条数达到 10 条时触发去重合并（上限 30 条），写入失败自动回滚

### Hook

```python
from dfagent.hook.hooks import register_hook, HookEvent

def my_hook(tool_call):
    if tool_call.name == "bash" and "curl" in tool_call.args.get("command", ""):
        return "禁止联网请求"        # 返回非 None 即阻断

register_hook(HookEvent.PreToolUse, my_hook)
```

| 事件 | 时机 | 返回值语义 |
| --- | --- | --- |
| `SessionStart` | 会话开始 | — |
| `UserPromptSubmit` | 收到用户消息后 | — |
| `PreToolUse` | 工具执行前 | 非 None 表示阻断，文本作为拒绝原因 |
| `PostToolUse` | 工具执行后 | — |
| `Stop` | 循环结束 | — |
| `DeBug` | 手动触发 | — |

内置 `PreToolUse` 钩子做三层权限检查：黑名单直接拒绝（`rm -rf /`、`sudo`、`mkfs` 等）、危险模式交互确认（`rm`、`chmod 777`）、文件路径越界交互确认。内置 `PostToolUse` 钩子对超 100000 字符的结果做截断。

### MCP 动态工具

工具不是一次性全量注入，而是按需加载：

1. `ensure_mcp_discovered()` 扫描 `.mcp.json`，逐个连接服务并拉取工具列表（单个服务失败不影响其他服务）
2. 模型调 `search_tool(query="天气")` 搜索工具元信息（不加载、不执行）
3. 模型调 `load_tool(name="get_weather")` 加载并注册，工具名冲突或来源服务不一致会拒绝
4. `ReActAgent._refresh_dynamic_tools()` 在下一轮请求前把已加载工具追加进模型工具列表

`MCPClient` 内部用一个常驻后台事件循环承载 SDK 的 async 会话，对外暴露同步的 `connect()` / `list_tools()` / `call_tool()`，并区分 `MCPConnectError` / `MCPTimeoutError` / `MCPNotConnectedError`。

### 后台任务

bash 工具传 `run_in_background=True` 时立即返回任务 ID，命令在线程中执行。每轮请求前 `inject_background_results()` 会把已完成任务以 `<task_notification>` 结构注入消息列表。

### Skills

在项目根目录建 `skills/<名字>/SKILL.md`：

```markdown
---
name: pdf
description: 处理 PDF 文件的步骤与注意事项
---

正文内容…
```

`list_skills()` 每次扫描目录（保证热更新），名字与描述进入 System Prompt，模型按需调 `load_skill` 取全文。

---

## 运行时配置

`src/dfagent/config/runtime_properties.py`：

| 常量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTNAME` | `"DFAgent"` | Agent 名，同时作为记忆根目录名 |
| `WORKDIR` | `Path.cwd()` | 工作目录，所有文件工具的沙箱根 |
| `CONTEXT_LIMIT` | `50000` | — |
| `KEEP_RECENT` | `20` | `micro_compact` 保留的最近工具结果数 |
| `PERSIST_THRESHOLD` | `30000` | 单个工具结果超此长度才触发持久化 |
| `TRANSCRIPT_DIR` | `.transcripts` | 压缩前的完整对话存档 |
| `TOOL_RESULTS_DIR` | `.task_outputs/tool-results` | 被持久化的工具结果 |
| `MAX_REACTIVE_RETRIES` | `5` | 连续对话失败的最大重试次数，超限抛 `RuntimeError` |
| `MAX_TOOL_OUTPUR_SIZE` | `100000` | 单个工具结果长度上限 |

`read` / `write` / `edit` 三个文件工具经由 `safe_path()` 校验，路径逃逸出 `WORKDIR` 会直接报错；`bash` 与 `grep` 以 `WORKDIR` 为 `cwd`，不做路径校验。

---

## TODO
- `ReActAgent._loop_anthropic` 为 TODO，当前会走到 `pass`（Anthropic 客户端下 `loop()` 返回 `None`）

