"""系统和当前工作目录参数查询工具。

供 agent 调用，查询：
  - 当前工作目录是否是 git 仓库
  - 当前平台（Platform）
  - 当前命令行解释器（Shell）
  - 操作系统版本
"""
import os
import platform
import subprocess
from pathlib import Path
from typing import Annotated

from dfagent.tools.tool import tool, Field


def is_git_repo(path: Path) -> bool:
    """判断目录是否是 git 仓库（支持子目录：向上查 .git）。"""
    current = path.resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return True
    return False


def get_shell() -> str:
    """获取当前命令行解释器，多来源兜底。"""
    # Windows 用 COMSPEC
    if os.name == "nt":
        return os.environ.get("COMSPEC", "unknown")

    # Unix: 优先 $SHELL，其次 /etc/passwd 中当前用户的登录 shell，最后 ps 兜底
    shell = os.environ.get("SHELL", "")
    if shell:
        return shell
    try:
        import pwd
        shell = pwd.getpwuid(os.getuid()).pw_shell
        if shell:
            return shell
    except (ImportError, KeyError):
        pass
    try:
        out = subprocess.run(
            ["ps", "-p", str(os.getppid()), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"

def get_platform():
    return platform.system().lower()


def get_os_version() -> str:
    """获取操作系统版本字符串。"""
    try:
        # 优先用详细版本，失败回退 platform.platform()
        return platform.platform()
    except Exception:
        return f"{platform.system()} {platform.release()}"


# @tool(name="system_info")
# def run_system_info(
#     action: Annotated[str, Field(
#         description="查询哪一项：git（是否 git 仓库）/ platform（平台）/ shell（命令行解释器）/ os（操作系统版本）/ all（全部）"
#     )] = "all",
# ) -> str:
#     """Query system and current working directory parameters.

#     Args:
#         action: One of 'git', 'platform', 'shell', 'os', or 'all'.
#     """
#     action = (action or "all").strip().lower()
#     cwd = Path.cwd()

#     if action == "git":
#         return f"git_repo: {_is_git_repo(cwd)}"
#     if action == "platform":
#         return f"platform: {platform.system()} {platform.machine()}"
#     if action == "shell":
#         return f"shell: {_get_shell()}"
#     if action == "os":
#         return f"os_version: {_get_os_version()}"
#     if action == "all":
#         lines = [
#             f"cwd: {cwd}",
#             f"git_repo: {_is_git_repo(cwd)}",
#             f"platform: {platform.system()} {platform.machine()}",
#             f"shell: {_get_shell()}",
#             f"os_version: {_get_os_version()}",
#         ]
#         return "\n".join(lines)

#     return (
#         "Error: 未知 action，可选值：git / platform / shell / os / all"
#     )
