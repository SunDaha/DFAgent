import threading
from dfagent.base.messages import ToolCall
from dfagent.tools.tool import ToolInfo
from typing import Callable

class BackgroundManager:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.results: dict[str, str] = {}
        self._ready: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()


    def start(self, tool_call:ToolCall, tool_info:ToolInfo) -> str:
        if tool_call.name != "bash":
            raise ValueError("Only Bash commands can run in the background")
        command = tool_call.args["command"]
        if not isinstance(command, str) or not command.strip():
                    raise ValueError("Bash command cannot be empty")
        with self._lock:
            self._counter += 1
            task_id = f"bg_{self._counter:04d}"
            self.tasks[task_id] = {
                            "tool_id": tool_call.id,
                            "command": command,
                            "status": "running",
                        }
            
            thread = threading.Thread(self._run, args=(task_id,tool_info.execute,tool_call.args))
            try:
                thread.start()
            except Exception as e:
                with self._lock:
                    self.tasks.pop(task_id)
                raise
        print(f"  [background] started {task_id}: {command[:60]}")
        return task_id
    
    def _run(self, task_id:str, function:Callable, param:dict):
        try:
            success, result = function(param)
            status = "completed" if success else "failed"
            if not success:
                result = f"Error: {result}"
        except Exception as e:
            result = f"Error: {type(e).__name__}: {e}"
            status = "failed"
        
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            task["status"] = status
            self.results[task_id] = str(result)
            self._ready.append(task_id)
    
    def collect(self) -> list[str]:
        with self._lock:
            ready = []
            for task_id in self._ready:
                task = self.tasks.pop(task_id,None)
                result = self.results.pop(task_id,"")
                if task is not None:
                    ready.append((task_id, task, result))
            self._ready.clear()
            
            notifications = []
            for task_id, task, result in ready:
                notifications.append(
                    f"<task_notification>\n"
                    f"  <task_id>{task_id}</task_id>\n"
                    f"  <status>{task['status']}</status>\n"
                    f"  <command>{task['command']}</command>\n"
                    f"  <summary>{result[:500]}</summary>\n"
                    f"</task_notification>"
                )
                print(f"  [background] collected {task_id}: {task['status']}")
            return notifications
    
    
BACKGROUND = BackgroundManager()
