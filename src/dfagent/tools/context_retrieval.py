"""
上下文召回TOOL    
"""
from dfagent.tools.tool import tool
from dfagent import TOOL_RESULTS_DIR

@tool(name="RetrieveToolResult", description="Retrieve a previously persisted tool result by file name.")
def retrieve_tool_result(file_name: str, offset: int = 0, limit: int | None = None) -> str:
    """Retrieve a previously persisted tool result by file name.

    Args:
        file_name: The name of the persisted tool result file in TOOL_RESULTS_DIR.
        offset: 0-indexed line number to start reading from. Defaults to 0.
        limit: Maximum number of lines to read. Defaults to None (read all).
    """
    # 确保目录存在
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = TOOL_RESULTS_DIR / file_name
    if not file_path.exists():
        return "Persisted tool result file not found"
    if file_path.is_dir():
        return f"Error: {file_name} is a directory, not a file"
    try:
        lines = []
        with file_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and (i - offset) >= limit:
                    lines.append(f"\n... [Truncated: limit of {limit} lines reached]")
                    break
                lines.append(line.rstrip("\n\r"))
        content = "\n".join(lines) if lines else "(empty file)"
        return str({
            "file": file_name,
            "offset": offset,
            "returned": len(lines),
            "content": content,
        })
    except Exception as e:
        return f"Error: Failed to read persisted tool result. Reason: {e}"
