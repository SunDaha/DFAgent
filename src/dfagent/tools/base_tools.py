import subprocess
import glob
from dfagent.tools.tool import tool
from pathlib import Path

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
def run_bash(command: str, timeout:int = 120000, run_in_background:bool = False) -> str:
    """Executes a bash command and returns its output.
    - Working directory persists between calls, but prefer absolute paths — `cd` in a compound command can trigger a permission prompt. Shell state (env vars, functions) does not persist; the shell is initialized from the user's profile.
    - IMPORTANT: Avoid using this tool to run `cat`, `head`, `tail`, `sed`, `awk`, or `echo` commands, unless explicitly instructed or after you have verified that a dedicated tool cannot accomplish your task. Instead, use the appropriate dedicated tool as this will provide a much better experience for the user.
    - Command output is displayed to you, not reliably to the user.
    - `timeout` is in milliseconds: default 120000, max 600000.

    Args:
        command: The command to execute
        timeout: Optional timeout in milliseconds (max 600000)
        run_in_background: When set to True, the command runs in the background, and the context is re-injected later (default is False)
    """
    
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /etc/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    # 毫秒转秒，且限制最大 600000ms
    timeout_ms = max(1, min(int(timeout), 600000))
    timeout_sec = timeout_ms / 1000
    try:
        r = subprocess.run(command, 
                           shell=True, 
                           cwd=WORKDIR,
                           capture_output=True, 
                           text=True,
                           encoding="utf-8", 
                           errors="replace", timeout=timeout_sec)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout_ms}ms)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

@tool(name="read")
def run_read(path: str, offset: int = 0, limit: int | None = None, pages:str = None) -> str:
    """
    Reads a file from the local filesystem.

    - `path` must be an absolute path.
    - Reads up to 2000 lines by default.
    - When you already know which part of the file you need, only read that part. This can be important for larger files.
    - Results are returned using cat -n format, with line numbers starting at 1
    - Reads images (PNG, JPG, …) and presents them visually. Reads PDFs via the `pages` parameter (e.g. "1-5", max 20 pages/request; required for PDFs over 10 pages). Reads Jupyter notebooks (.ipynb) as cells with outputs.
    - Reading a directory, a missing file, or an empty file returns an error or system reminder rather than content.
    - Do NOT re-read a file you just edited to verify — Edit/Write would have errored if the change failed, and the harness tracks file state for you.

    Args:
        path: The path of the file to read.
        offset: The 0-indexed line number to start reading from.
        limit: Maximum number of lines to read.
        pages: PDF page range (e.g., "1-5", max 20 pages/request; required for PDFs over 10 pages).
    """
    try:
        file_path = safe_path(path)
        # 普通文件
        if file_path.is_file() and file_path.suffix.lower() != ".pdf":
            lines = []
            with file_path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < offset:
                        continue
                    if limit is not None and (i - offset) >= limit:
                        lines.append(f"\n... [Truncated: limit of {limit} lines reached]")
                        break
                    lines.append(line.rstrip('\n\r'))
            return "\n".join(lines) if lines else "(empty file)"

        # PDF
        if file_path.suffix.lower() == ".pdf" and file_path.is_file():
            return _read_pdf(file_path, pages)

        if file_path.is_dir():
            return f"Error: {path} is a directory, not a file"
        return f"Error: {path} not found"
    except Exception as e:
        return f"Error: Failed to read file. Reason: {e}"


def _read_pdf(path: Path, pages: str | None) -> str:
    try:
        from pypdf import PdfReader
    except Exception as e:
        return f"Error: PDF support unavailable: {e}"

    try:
        reader = PdfReader(str(path))
        total = len(reader.pages)

        if total == 0:
            return "(empty PDF)"

        # 超过 10 页时必须传 pages
        if total > 10 and not pages:
            return f"Error: PDF has {total} pages; set `pages` (e.g., '1-5')"

        start, end = 1, total
        if pages:
            try:
                if "-" in str(pages):
                    s, e = str(pages).split("-", 1)
                    start, end = int(s), int(e)
                else:
                    start = end = int(pages)
                start = max(1, start)
                end = min(end, total)
                if start > end:
                    start, end = end, start
            except Exception:
                return f"Error: Invalid pages={pages}"

        max_pages = 20
        if (end - start + 1) > max_pages:
            end = start + max_pages - 1

        parts = [f"PDF: {path.name} ({total} pages)"]
        for i in range(start - 1, end):
            parts.append(f"\n--- Page {i+1} ---\n")
            try:
                parts.append(reader.pages[i].extract_text() or "(no text)")
            except Exception as e:
                parts.append(f"(extract failed: {e})")
        return "".join(parts)
    except Exception as e:
        return f"Error: Failed to read PDF. Reason: {e}"


@tool(name="write")
def run_write(path: str, content: str) -> str:
    """
    Writes a file to the local filesystem, overwriting if one exists.
    When to use: creating a new file, or fully replacing one you've already Read. Overwriting an existing file you haven't Read will fail. For partial changes, use Edit instead.

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
def run_edit(path: str, old_string: str, new_string: str, replace_all:bool = False) -> str:
    """Performs exact string replacement in a file.
    
    - You must Read the file in this conversation before editing, or the call will fail.
    - `old_string` must match the file exactly, including indentation, and be unique — the edit fails otherwise. Strip the Read line prefix (line number + tab) before matching.
    - `replace_all: true` replaces every occurrence instead.
    
    Args:
        path: The absolute path to the file to modify
        old_string: The text to replace
        new_string: The text to replace it with (must be different from old_string)
        replace_all: if true, replace every occurrence; if false (default), replace only the first match, and error if multiple matches exist.
    """
    try:
        file_path = safe_path(path)
        with file_path.open("r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return f"Error: Text not found in {path}"
        if replace_all:
            content = content.replace(old_string, new_string)
        else:
            if count > 1:
                return f"Error: Found {count} matches; old_string must be unique or set replace_all=true"
            content = content.replace(old_string, new_string, 1)
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return f"Edited {path}: replaced '{old_string}' with '{new_string}'"
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