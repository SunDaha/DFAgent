import re
import json
import threading
import time
from pathlib import Path
from dfagent import WORKDIR
from dfagent.utils.valid_info import is_valid_agent_name



# -- MessageBus and Team Protocols --


MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_ROOT = MAILBOX_DIR.resolve()
RESERVED_TEAMMATE_NAMES = {"lead", "agent"}


class MessageBus:
    """Thread-safe file mailboxes with destructive reads."""
    
    def __init__(self):
            self._lock = threading.RLock()
            self._changed = threading.Condition(self._lock)

    def _path(self, agent:str):
        if not is_valid_agent_name(agent):
            raise ValueError(f"Invalid mailbox recipient: {agent!r}")
        path = (MAILBOX_DIR / f"{agent}.jsonl").resolve()
        if not path.is_relative_to(MAILBOX_ROOT):
            raise ValueError(f"Mailbox path escapes directory: {agent!r}")
        return path
    
    def _read_unlocked(self, agent:str) -> list[dict]:
        inbox = self._path(agent)
        if not inbox.exists():
            return []
        msg = [json.loads(line) for line in inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        inbox.unlink()
        return msg
        
    
    def send(self, from_agent:str, to_agent:str, content:str, msg_type:str = "message", metadata:dict | None = None):
        msg = {
            "from_agent":from_agent,
            "to_agent":to_agent,
            "msg_type":msg_type,
            "content":content,
            "time":time.time(),
            "metadata":metadata,
        }
        with self._changed:
            with self._path(to_agent).open("a", encoding="utf-8") as handler:
                handler.write(json.dumps(msg, ensure_ascii=True) + "\n")
            self._changed.notify_all()
        print(f"  [bus] {from_agent} -> {to_agent}: "
            f"({msg_type}) {content[:50]}")
    
    def read_inbox(self, agent:str) -> list[dict]:
        with self._lock:
            return self._read_unlocked(agent)
    
    def peek(self, agent:str) -> bool:
        with self._lock:
            path = self._path(agent)
            return path.exists() and path.stat().st_size() > 0
    
    def wait_messages_send(self, agent: str,
                          timeout: float | None = None) -> list[dict]:
        """Block until the agent has messages or timeout expires."""
        deadline = time.monotonic() + timeout if timeout else None
        with self._changed:
            while not self.peek(agent):
                remaining = deadline - time.monotonic() if deadline else None
                if remaining and remaining <= 0:
                    return []
                self._changed.wait()
            return self._read_unlocked(agent)

BUS = MessageBus()

