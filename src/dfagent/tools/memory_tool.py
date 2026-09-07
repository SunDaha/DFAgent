from dfagent.tools.tool import tool
from dfagent.memory.memory import list_memory_files, read_memory_file, memory_slug


@tool(name="read_memory")
def read_memory(name: str | None = None) -> str:
    """Read a memory record by name, or list all memories.

    Args:
        name: The memory name (or filename) to read. Omit to list all memories.
    """
    records = list_memory_files()
    if not records:
        return "(no memories stored)"

    if name is None or not name.strip():
        lines = [f"- {r['name']}: {r['description']}" for r in records]
        return "\n".join(lines)

    target = name.strip()
    for r in records:
        if target == r["name"] or target == r["filename"] or target == memory_slug(r["name"]):
            content = read_memory_file(r["filename"])
            return content or f"Error: memory file {r['filename']} is empty"

    available = ", ".join(r["name"] for r in records)
    return f"Error: no memory named '{name}'. Available: {available}"

