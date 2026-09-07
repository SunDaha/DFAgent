from dfagent.tools.tool import tool, Field
from typing import Annotated
import ast ,json



CURRENT_TODOS: list[dict] = []


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

    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "task" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'task' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed", "cancelled"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None



@tool(name="write_todo", description="Create and manage the task list for the current session. Replace the old list with each call to pass the complete task list.")
def run_write_todo_tool(
    todos: Annotated[list, Field(
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
    global CURRENT_TODOS
    todos ,error = _normalize_todos(todos)
    if error:
        return error
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m", "cancelled": "\033[31m✗\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['task']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"


