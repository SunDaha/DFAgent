import subprocess
import glob
from dfagent.tools.tool import tool
from pathlib import Path
from typing import Annotated

WORKDIR = Path.cwd()

# 工具搜索默认排除的目录（避免 .venv/.git/__pycache__ 噪音）
EXCLUDED_DIRS = (".venv", ".git", "__pycache__", "node_modules", ".task_outputs", ".transcripts", ".memory")


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError("Path is outside of work directory")
    return path


# 基本工具定义
@tool(name="bash")
def run_bash(command: str) -> str:
    """Run a shell command.

    Args:
        command: The shell command to execute.
    """
    
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /etc/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

@tool(name="read")
def run_read(path: str, offset: int = 0, limit: int | None = None) -> str:
    """
    读取指定文件的内容。

    Args:
        path: The path of the file to read.
        offset: The 0-indexed line number to start reading from.
        limit: Maximum number of lines to read.
    """
    try:
        # safe_path 返回经过安全校验的 pathlib.Path 对象
        file_path = safe_path(path)
        lines = []

        with file_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and (i - offset) >= limit:
                    lines.append(f"\n... [Truncated: limit of {limit} lines reached]")
                    break

                lines.append(line.rstrip('\n\r'))

        return "\n".join(lines)

    except Exception as e:
        return f"Error: Failed to read file. Reason: {e}"


@tool(name="write")
def run_write(path: str, content: str) -> str:
    """Write content to a file.

    Args:
        path: The path of the file to write.
        content: The content to write to the file.
    """
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True) # 创建此文件需要的父级目录
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: Failed to write file. Reason: {e}"


@tool(name="edit")
def run_edit(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing old_text with new_text.
    
    Args:
        path: The path of the file to edit.
        old_text: The exact text to replace.
        new_text: The replacement text.
    
    """
    try:
        file_path = safe_path(path)
        with file_path.open("r", encoding="utf-8") as f:
            content = f.read()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        content = content.replace(old_text, new_text)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return f"Edited {path}: replaced '{old_text}' with '{new_text}'"
    except Exception as e:
        return f"Error: Failed to edit file. Reason: {e}"


@tool(name="glob")
def run_glob(pattern: str, recursive: bool = True, limit: int = 200) -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: The glob pattern to search for files. Use ** for recursive search.
        recursive: Whether to search subdirectories recursively.
        limit: Maximum number of results to return.

    """
    results = []
    for match in glob.glob(pattern, root_dir=WORKDIR, recursive=recursive):
        if any(d in Path(match).parts for d in EXCLUDED_DIRS):
            continue
        results.append(match)
        if len(results) >= limit:
            results.append(f"... [Truncated: limit of {limit} results reached]")
            break
    return "\n".join(results) if results else "(no matches)"
    
    

@tool(name="grep")
def run_grep(pattern: str, path: str = ".", max_results: int = 200) -> str:
    """Search file contents for a regex pattern, excluding virtualenv/cache/git dirs.

    Args:
        pattern: The regex pattern to search for.
        path: The directory or file to search in (default: workspace root).
        max_results: Maximum number of matching lines to return.
    """
    cmd = ["grep", "-rn", "-I", "-E", "--color=never"]
    for d in EXCLUDED_DIRS:
        cmd += ["--exclude-dir", d]
    cmd += ["--exclude", "*.pyc", "-e", pattern, path]
    try:
        r = subprocess.run(cmd, cwd=WORKDIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode == 2:
            return f"Error: {r.stderr.strip()[:500] or 'grep failed'}"
        out = (r.stdout or "").strip()
        if not out:
            return "(no matches)"
        lines = out.splitlines()
        if len(lines) > max_results:
            total = len(lines)
            lines = lines[:max_results]
            lines.append(f"... [Truncated: {total} results, showing {max_results}]")
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "Error: Timeout (30s)"
    except Exception as e:
        return f"Error: {e}"


@tool(name="compact",description="Compress conversation history to save context space. Call with 1 when context is too long.")
def run_compact(trigger: int = 1):
    """Compress conversation history to free context space.

    Args:
        trigger: Send 1 to compact.
    """
    return None  # agent_loop 拦截后手动处理