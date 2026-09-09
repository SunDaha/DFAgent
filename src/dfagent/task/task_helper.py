import json
from dataclasses import asdict
from dfagent import WORKDIR
from dfagent.task.task import Task, TaskStatus, TaskStore

TASK_DIR = WORKDIR / ".task"
TASKS = TaskStore(TASK_DIR)


def create_task(subject: str, description: str = "") -> Task:
    return TASKS.create(subject, description)

def update_task(task_id: str, addBlockedBy: list[str]) -> Task:
    return TASKS.update_dependencies(task_id, addBlockedBy)

def load_task(task_id: str) -> Task:
    return TASKS.load(task_id)

def list_tasks() -> list[Task]:
    return TASKS.list()

def get_task(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def incomplete_dependencies(task: Task) -> list[str]:
    """获取此任务还没完成的前置任务"""
    incomplete = []
    for dependency in task.blockedBy:
        if load_task(dependency).status != TaskStatus.COMPLETED:
            incomplete.append(dependency)
    return incomplete

def can_start(task_id: str) -> bool:
    return not incomplete_dependencies(load_task(task_id))

def claim_task(task_id: str, owner: str = "agent") -> str:
    """认领/开始一个任务"""
    task = load_task(task_id)
    if task.status != TaskStatus.PENDING:
        return f"Task {task_id} is {task.status}, cannot claim"
    dependencies = incomplete_dependencies(task)
    if dependencies:
        return f"Blocked by: {dependencies}"
    task.owner = owner
    task.status = TaskStatus.IN_PROGRESS
    TASKS.save(task)
    print(f"  [claim] {task.subject} -> in_progress (owner: {owner})")
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str, owner: str = "agent") -> str:
    """完成任务,并返回他的下游可执行任务ID列表"""
    task = load_task(task_id)
    if task.status != TaskStatus.IN_PROGRESS:
        return f"Task {task_id} is {task.status}, cannot complete"
    if task.owner != owner:
        return f"Task {task_id} is owned by {task.owner}, not {owner}"
    ready_before = {
        candidate.id
        for candidate in list_tasks()
        if candidate.status == TaskStatus.PENDING
        and candidate.blockedBy
        and can_start(candidate.id)
    }
    task.status = TaskStatus.COMPLETED
    TASKS.save(task)
    unblocked = [candidate.subject for candidate in list_tasks()
                 if candidate.status == TaskStatus.PENDING
                 and candidate.blockedBy
                 and candidate.id not in ready_before
                 and can_start(candidate.id)]
    print(f"  [complete] {task.subject}")
    message = f"Completed {task.id} ({task.subject})"
    if unblocked:
        message += f"\nUnblocked: {', '.join(unblocked)}"
        print(f"  [unblocked] {', '.join(unblocked)}")
    return message

