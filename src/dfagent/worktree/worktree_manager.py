import re
import subprocess
from dfagent import WORKDIR
from pathlib import Path
from dfagent.utils.git import run_git

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





def _get_all_worktrees() -> tuple[dict[Path, dict[str, str]], str | None]:
    ok, result = run_git(["worktree", "list", "--porcelain"])
    if not ok:
        return {}, f"cannot read Git worktree registry: {result}"
    entries: dict[Path, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in result.splitlines() + [""]:
        if not line:
            raw_path = current.get("worktree")
            if raw_path:
                entries[Path(raw_path).resolve()] = current
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return entries, None


def get_worktree(name: str) -> tuple[Path | None, str | None]:
    try:
        path = _worktree_path(name)
    except ValueError as exc:
        return None, str(exc)
    entries, error = _get_all_worktrees()
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



def create_worktree(name: str) -> str:
    # 1.验证工作目录名字
    error= vaild_worktree_name(name)
    if error:
        return f"Error: {error}"
    # 2.获取工作目录
    try:
        path = _worktree_path(name)
    except Exception as error:
        return f"Error: {error}"
    # 3.获取分支名称
    branch = _worktree_branch(name)
    
    if path.exists():
        return f"Error: Worktree path already exists: {path}"
    ok, result = run_git(["rev-parse", "--show-toplevel"])
    if not ok or Path(result).resolve() != WORKDIR.resolve():
        return "Error: Working directory must be the root of a Git repository"
    ok, _ = run_git(["check-ref-format", "--branch", branch])
    if not ok:
        return f"Error: Invalid branch '{branch}'"

    exists, _ = run_git([
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}"
    ])
    
    if exists:
        return f"Error: Branch '{branch}' already exists"

    ok, result = run_git([
        "worktree",
        "add",
        "-b",
        branch,
        str(path),
        "HEAD"
    ])

    if not ok:
        return f"Git error: {result}"
    
def remove_worktree(name: str, force: bool = False) -> str:
    try:
        path = _worktree_path(name)
        branch = _worktree_branch(name)
    except Exception as error:
        return f"Error: {error}"    
    
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    # 删除 worktree
    ok, result = run_git(args)
    if not ok:
        return f"Git error: {result}"
    
    # 删除 branch
    args = ["branch", "--delete"]
    if force:
        args.append("--force")
    args.append(branch)
    ok, result = run_git(args)
    if not ok:
        return f"Git error: {result}"
    return f"Worktree '{name}' removed"