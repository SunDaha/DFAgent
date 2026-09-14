import copy
import secrets
import string
from openai import OpenAI
from anthropic import Anthropic
from dfagent import MAX_REACTIVE_RETRIES
from dfagent.base.model import Model
from dfagent.base.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from dfagent.prompt.prompt_builder import build_system
from dfagent.context.context_compact import tool_result_budget, snip_compact, micro_compact, compact_history
from dfagent.hook.hooks import trigger_hooks, HookEvent
from dfagent.memory.memory import extract_memories, consolidate_memories
from dfagent.tools.tool_manager import execute_batch_tool,inject_background_results
from dfagent.tools.write_todo_tool import TodoState

class Agent:
    id:str
    model: Model
    def generate_agent_id(length=6):
        # 定义字符集：小写字母 + 数字
        chars = string.ascii_lowercase + string.digits
        # 从字符集中随机抽取 length 个字符
        random_str = ''.join(secrets.choice(chars) for _ in range(length))
        return f"agent_{random_str}"
    
class ReActAgent(Agent):
    todo_remind_interval = 3       # 连续多少轮未用 write_todo 触发提醒

    def __init__(self, 
                 client: OpenAI | Anthropic,         # LLM client
                 model_name:str | None = None,       # 模型名字
                 thinking_effort:str | None = None,  # 思考
                 tools:list[dict] | None = None,      # 基础工具
                 ):
        # 命名ID
        self.id = self.generate_agent_id()
        
        # 封装model
        self.model = Model(
            client=client,
            model=model_name,
            tools=tools or [],
            thinking_effort=thinking_effort,
        )
        
        # write_todo 状态
        self.todo_state = TodoState()
        
        # 当前错误重试次数
        self.reactive_retries = 0


    def _maybe_remind_write_todo(self, messages: list[BaseMessage]):
        """todo 未完成且连续多轮未用 write_todo 时，在末尾追加提醒。"""
        if not self.todo_state.active or not self.todo_state.has_incomplete():
            self.todo_state.active = False
            return
        if self.todo_state.rounds_since_update >= self.todo_remind_interval:
            messages.append(HumanMessage(
                content="The current task list has not yet been fully completed, and `write_todo` has not been called to update progress for several consecutive rounds."
                        "Please proceed after using the `write_todo` tool to synchronize task statuses in this round."
            ))
            self.todo_state.rounds_since_update = 0


    def _loop_openai(self, messages:list[BaseMessage]):
        # 用户提示词输入钩子
        if isinstance(messages[-1],HumanMessage):
            trigger_hooks(HookEvent.UserPromptSubmit,messages)
        
        # 构建系统词语
        system_prompt = SystemMessage(content=build_system(messages))
        if messages and messages[0].get_role() == "system":
            messages[0] = system_prompt
        else:
            messages.insert(0,system_prompt)
            
        while True:
            # 1.上文压缩
            original_messages = copy.deepcopy(messages)
            
            # 最近的工具调用结果(tool_call(end)-assistant_tool_call) 超出预算就写入文件
            messages[:] = tool_result_budget(messages)
            # 排除开头和结尾的内容，压缩中间内容
            messages[:] = snip_compact(messages)
            # 保留最近20条且长度小于120的调用工具的结果，其他结果使用占位符
            messages[:] = micro_compact(messages)
            
            # 注入后台运行完成的bash工具结果
            inject_background_results(messages)
            # 2.发送对话
            try:
                # write_todo 未完成且连续多轮未更新 → 追加提醒再对话
                self._maybe_remind_write_todo(messages)
                ai_message = self.model.chat(messages,max_tokens=100000)
                # messages 添加LLM对话结果
                messages.append(ai_message)
                self.reactive_retries = 0
            except Exception as e:
                if self.reactive_retries < MAX_REACTIVE_RETRIES:
                    if ("prompt_too_long" in str(e).lower() or "too many tokens" in str(e).lower()):
                        messages[:] = compact_history(messages)
                    self.reactive_retries += 1
                    continue
                raise RuntimeError(
                    f"连续 {MAX_REACTIVE_RETRIES} 次对话失败，终止: {e}"
                ) from e
            
            # 3.调用工具
            # write_todo 循环 + 1
            if self.todo_state.active:
                self.todo_state.rounds_since_update += 1
            tool_calls = ai_message.get_tool_calls()
            # 无工具调用停止循环
            if not tool_calls:
                trigger_hooks(HookEvent.Stop, messages)
                extract_memories(original_messages)
                consolidate_memories()
                return ai_message.get_content()
            
            tool_message = execute_batch_tool(tool_calls=tool_calls, todo_state=self.todo_state)
            # messages 添加工具调用结果
            messages.append(tool_message)
            
            
    def _loop_anthropic(self,messages:list[BaseMessage]):
        # TODO
        pass
    
    
    def loop(self, messages:list[BaseMessage]):
        client = self.model.client
        if isinstance(client, OpenAI):
            return self._loop_openai(messages)
        elif isinstance(client, Anthropic):
            return self._loop_anthropic(messages)
        else:
            return self._loop_openai(messages)




class ReflexionAgent(Agent):
    pass


class PlanAndExecuteAgent(Agent):
    pass
