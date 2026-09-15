from dfagent.tools.tool import tool, Field
from dataclasses import dataclass,field
from typing import Annotated, Literal
import ast ,json, copy
from pydantic import BaseModel, ConfigDict, Field as PydanticField


@dataclass
class TodoState:
    """单个 Agent 独有的任务列表状态。"""

    items: list[dict] = field(default_factory=list)
    rounds_since_update: int = 0
    active: bool = False

    def has_incomplete(self) -> bool:
        """todo 是否仍未执行完：存在 pending / in_progress 任务即视为未完。"""
        return any(
            isinstance(item, dict)
            and item.get("status") in ("pending", "in_progress")
            for item in self.items
        )

    def replace(self, items: list[dict]) -> None:
        self.items = copy.deepcopy(items)
        self.rounds_since_update = 0
        self.active = bool(self.items)


class TodoItem(BaseModel):
    """单个 Todo 项，负责运行时结构校验。"""

    model_config = ConfigDict(extra="forbid")

    task: str = PydanticField(min_length=1)
    status: Literal["pending", "in_progress", "completed", "cancelled"]



def _normalize_todos(todos): 
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
            
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"

    normalized = []
    for i, item in enumerate(todos):
        try:
            todo = item if isinstance(item, TodoItem) else TodoItem.model_validate(item)
        except Exception as error:
            return None, f"Error: todos[{i}] is invalid: {error}"
        normalized.append(todo.model_dump())
    return normalized, None



@tool(name="write_todo", description="Create and manage the task list for the current session. Replace the old list with each call to pass the complete task list.")
def run_write_todo_tool(
    todos: Annotated[list[TodoItem], Field(
        description="Complete list of all current tasks",
        json_schema={
            "items": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Task description",
                        "minLength": 1,
                    },
                    "status": {
                        "type": "string",
                        "description": "Task status",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                    },
                },
                "required": ["task", "status"],
                "additionalProperties": False,
            }
        }
    )]
) -> str:
    todos, error = _normalize_todos(todos)
    if error:
        raise ValueError(f"Error:{error}")
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in todos:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m", "cancelled": "\033[31m✗\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['task']}")
    print("\n".join(lines))
    return f"Updated {len(todos)} tasks"
