from dfagent.base.messages import ToolCall
from dfagent.config.runtime_properties import WORKDIR

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

# PreToolUse
def permission_check_hook(tool_call:ToolCall):
    """PreToolUse: 基于黑名单 + 危险模式 + 路径越界的权限检查。

    Args:
        tool_call: 统一 ToolCall 对象

    Returns:
        None — 通过检查
        str  — 拒绝原因
    """
    tool_name = getattr(tool_call, "name", None)
    tool_args = getattr(tool_call, "args", None)
    
    # 1.bash检查
    if tool_name == "bash":
        if tool_args:
            command = tool_args.get("command", "")
            # 闸门1: 黑名单 — 直接拒绝
            for pattern in DENY_LIST:
                if pattern in command:
                    print(f"\n\033[31m Blocked: '{pattern}' found in command\033[0m")
                    return f"Permission denied: '{pattern}' is on the deny list"
            # 闸门2: 危险模式 — 询问用户
            for kw in DESTRUCTIVE:
                if kw in command:
                    print(f"\n\033[33m Potentially destructive: '{kw}'\033[0m")
                    print(f"   Command: {command}")
                    choice = input("   Allow? [y/N] ").strip().lower()
                    if choice not in ("y", "yes"):
                        return "Permission denied by user"
        else:
            return None

    # 2.文件路径越界检查
    if tool_name in ("read", "write", "edit"):
        path = tool_args.get("path", "")
        try:
            resolved = (WORKDIR / path).resolve()
            if not resolved.is_relative_to(WORKDIR):
                print(f"\n\033[33m⚠  Path outside workspace: {path}\033[0m")
                choice = input("   Allow? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
        except (ValueError, OSError):
            return f"Invalid path: {path}"
    return None




def log_hook(tool_call:ToolCall) -> None:
    """PreToolUse: 日志记录钩子。"""
    tool_args = getattr(tool_call,"args", None)
    if tool_args:
        args_preview = list(tool_args.items())[:3]
        print(f"\033[90m[HOOK] Args: {tool_call.args}, Arguments: {args_preview}\033[0m")
    return None

