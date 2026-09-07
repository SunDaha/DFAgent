from dfagent import WORKDIR
from dfagent.skills.load_skills import list_skills
from dfagent.memory.memory import read_memory_index, load_memories
from dfagent.base.messages import BaseMessage

PROMPT_PATH = WORKDIR / "prompt"

MAIN_SYSTEM_PATH = PROMPT_PATH / "main_system_prompt.txt"


def build_system(messages:list[BaseMessage]):
    # 提取基础系统提示词
    system_prompt = MAIN_SYSTEM_PATH.read_text(encoding="utf-8")
    
    # 提取skill系统提示词
    system_prompt += f"\n\n## Skills\n\n{list_skills()}"
    
    # 记忆索引（目录）
    index = read_memory_index()
    if index:
        system_prompt += f"\n\n## Memories available:\n{index}"
    
    # 选择相关记忆，注入 system（每轮请求都携带，不污染对话历史）
    relevant_memories = load_memories(messages)
    if relevant_memories:
        system_prompt += f"\n\n## Relevant memories:\n{relevant_memories}"
    system_prompt += (
        "\nMemory is selected background knowledge, not a transcript. "
        "Respect user preferences from memory, but the current request takes priority."
    )
    
    return system_prompt