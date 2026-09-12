import re
import subprocess
from dfagent import WORKDIR
from pathlib import Path

WORKTREES_DIR = WORKDIR / ".worktrees"  #
WORKTREES_ROOT = WORKTREES_DIR.resolve()#

VALID_WORKTREE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def vaild_worktree_name(name:str) -> str:
    """验证worktree名字是否符合规则

    Args:
        name (str): worktree name

    Returns:
        str: 名字是正确的返回None 错误返回出错问题
    """
    if not isinstance(name, str) or not VALID_WORKTREE_NAME.fullmatch(name):
        return ("worktree name must be 1-64 letters, digits, dots, "
                "underscores, or dashes, and start with a letter or digit")
    if name in {".", ".."} or ".." in name:
        return "worktree name cannot contain '..'"
    return None


def _worktree_path(name:str) -> Path:
    """获取worktree目录

    Args:
        name (str): worktree name

    Returns:
        Path: worktree目录
    """
    path = (WORKTREES_DIR / name).resolve()
    if not path.is_relative_to(WORKTREES_ROOT) or path == WORKTREES_ROOT:
        raise ValueError(f"Worktree path escapes directory: {name!r}")
    return path


def _worktree_branch(name: str) -> str:
    """获取worktree分支名字

    Args:
        name (str): worktree name

    Returns:
        str: worktree分支名字
    """
    return f"wt/{name}"


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """运行Git命令"""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd or WORKDIR,
            capture_output=True, text=True, errors="replace", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output or "(no output)"


def _registered_worktrees() -> tuple[dict[Path, dict[str, str]], str | None]:
    """获取当前工作目录下的所有worktree信息"""
    ok, output = _run_git(["worktree", "list", "--porcelain"])
    if not ok:
        return {}, f"cannot read Git worktree registry: {output}"
    entries: dict[Path, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in output.splitlines() + [""]:
        if not line:
            raw_path = current.get("worktree")
            if raw_path:
                entries[Path(raw_path).resolve()] = current
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return entries, None


def registered_worktree(name: str) -> tuple[Path | None, str | None]:
    """通过 worktree name 获取 worktree 路径

    Args:
        name (str): worktree name

    Returns:
        tuple[Path | None, str | None]: worktree 路径
    """
    try:
        path = _worktree_path(name)
    except ValueError as exc:
        return None, str(exc)
    entries, error = _registered_worktrees()
    if error:
        return None, error
    if path not in entries:
        return None, f"worktree '{name}' is not registered with Git"
    if not path.is_dir():
        return None, f"worktree '{name}' is missing at {path}"
    expected_branch = f"refs/heads/{_worktree_branch(name)}"
    if entries[path].get("branch") != expected_branch:
        return None, (f"worktree '{name}' is not registered on expected "
                      f"branch '{_worktree_branch(name)}'")
    return path, None


def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    """运行Git命令"""
    ok, output = _run_git(args, cwd)
    return ok, output[:5000]



    