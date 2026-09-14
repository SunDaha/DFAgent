from dfagent.tools.tool import tool
from dfagent.agent_team.team_manager import create_task, update_task, list_tasks, claim_task, complete_task


@tool(name="create_task")
def run_create_task(subject: str, description: str = "") -> str:
    """Create a new task and return its ID and subject.

    Args:
        subject: The task title (non-empty).
        description: Optional detailed description of the task.
    """
    task = create_task(subject, description)
    print(f"  [create] {task.subject}")
    return f"Created Task {task.id}: {task.subject}"

@tool(name="update_task")
def run_update_task(task_id: str, addBlockedBy: list[str]) -> str:
    """Add dependencies (blockedBy) to a task and return the updated list.

    Args:
        task_id: The target task ID (e.g. task_xxxxxxxx).
        addBlockedBy: List of task IDs this task depends on. The target must be
            pending and unowned; each dependency must exist and not form a cycle.
    """
    task = update_task(task_id, addBlockedBy)
    dependencies = ", ".join(task.blockedBy) or "(none)"
    print(f"  [update] {task.subject} blockedBy: {dependencies}")
    return f"Updated {task.id} blockedBy: {dependencies}"

@tool(name="list_tasks")
def run_list_tasks() -> str:
    """List all tasks with their status, dependencies, and owner.

    Returns:
        Multi-line text, one task per line; a hint when there are no tasks.
    """
    tasks = list_tasks()
    if not tasks:
        return "No tasks. Use create_task to add some."
    lines = []
    for task in tasks:
        marker = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }.get(task.status, "[?]")
        dependencies = (
            f" (blockedBy: {', '.join(task.blockedBy)})"
            if task.blockedBy else ""
        )
        owner = f" [{task.owner}]" if task.owner else ""
        lines.append(
            f"{marker} {task.id}: {task.subject} "
            f"[{task.status}]{owner}{dependencies}"
        )
    return "\n".join(lines)

@tool(name="claim_task")
def run_claim_task(task_id: str) -> str:
    """Claim ownership of a pending task and mark it as in_progress.

    - Fails if the task is not pending.
    - Fails if the task has incomplete dependencies (blockedBy tasks that are not completed).
    - On success, sets owner to 'agent' and status to 'in_progress'.

    Args:
        task_id: The task ID to claim (e.g., task_xxxxxxxx).

    Returns:
        str: Success message with task id and subject, or an error explaining why it cannot be claimed.
    """
    return claim_task(task_id=task_id, owner="agent")

@tool(name="complete_task")
def run_complete_task(task_id: str) -> str:
    """Complete a task that is currently in_progress and owned by the agent.

    - Fails if the task is not in_progress.
    - Fails if the task is not owned by the agent.
    - On success, sets status to 'completed' and returns a list of downstream tasks that became unblocked.

    Args:
        task_id: The task ID to complete (e.g., task_xxxxxxxx).

    Returns:
        str: Success message with task id and subject, plus any unblocked tasks, or an error explaining why it cannot be completed.
    """
    return complete_task(task_id, owner="agent")
    

