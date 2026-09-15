import subprocess
from pathlib import Path
from dfagent import WORKDIR

def run_git(args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
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
