"""
MCP server for the todo app.

Exposes tools and resources for managing projects and tasks
via the Model Context Protocol.
"""

from mcp.server.fastmcp import FastMCP

from todo.core.manager import TodoManager
from todo.ui.tasks import (
    parse_tasks_from_file,
    add_task_to_file,
    toggle_task_in_file,
    edit_task_in_file,
    remove_task_from_file,
)

mcp = FastMCP("todo")


def _get_manager():
    return TodoManager()


def _find_task_by_id(project_path, project_name, task_id):
    """Find a TaskRef by its task_id (hex ID from <!-- todo:id=XXXX -->)."""
    tasks = parse_tasks_from_file(project_path, project_name)
    for t in tasks:
        if t.task_id == task_id:
            return t
    return None


# ── Tools ──────────────────────────────────────────────────


@mcp.tool()
def list_projects() -> list[dict]:
    """List all projects with name and task counts (pending/done)."""
    manager = _get_manager()
    projects = manager.list_projects()
    result = []
    for p in projects:
        path = manager.get_project_path(p["name"])
        tasks = parse_tasks_from_file(path, p["name"])
        done = sum(1 for t in tasks if t.checked)
        pending = len(tasks) - done
        result.append({
            "name": p["name"],
            "pending": pending,
            "done": done,
        })
    return result


@mcp.tool()
def list_tasks(project: str) -> list[dict]:
    """List all tasks for a project with id, text, checked state, indent level, and task_id."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return [{"error": f"Project '{project}' not found"}]
    tasks = parse_tasks_from_file(path, project)
    return [
        {
            "index": i,
            "text": t.text,
            "checked": t.checked,
            "indent": len(t.indent),
            "task_id": t.task_id,
        }
        for i, t in enumerate(tasks)
    ]


@mcp.tool()
def add_task(project: str, text: str, parent_task_id: str = None) -> dict:
    """Add a new task to a project. If parent_task_id is given, adds as a child of that task."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return {"error": f"Project '{project}' not found"}

    after_line = None
    indent = ""
    if parent_task_id:
        parent = _find_task_by_id(path, project, parent_task_id)
        if not parent:
            return {"error": f"Task with id '{parent_task_id}' not found"}
        after_line = parent.line_no
        indent = parent.indent + "    "

    add_task_to_file(path, text, indent=indent, after_line=after_line)
    return {"status": "ok", "project": project, "text": text}


@mcp.tool()
def toggle_task(project: str, task_id: str) -> dict:
    """Toggle a task's checked state by task_id."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return {"error": f"Project '{project}' not found"}

    task = _find_task_by_id(path, project, task_id)
    if not task:
        return {"error": f"Task with id '{task_id}' not found"}

    new_state = toggle_task_in_file(path, task.line_no)
    return {"status": "ok", "task_id": task_id, "checked": new_state}


@mcp.tool()
def edit_task(project: str, task_id: str, new_text: str) -> dict:
    """Edit a task's text by task_id."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return {"error": f"Project '{project}' not found"}

    task = _find_task_by_id(path, project, task_id)
    if not task:
        return {"error": f"Task with id '{task_id}' not found"}

    success = edit_task_in_file(path, task.line_no, new_text)
    if not success:
        return {"error": "Failed to edit task"}
    return {"status": "ok", "task_id": task_id, "new_text": new_text}


@mcp.tool()
def remove_task(project: str, task_id: str) -> dict:
    """Remove a task by task_id."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return {"error": f"Project '{project}' not found"}

    task = _find_task_by_id(path, project, task_id)
    if not task:
        return {"error": f"Task with id '{task_id}' not found"}

    success = remove_task_from_file(path, task.line_no)
    if not success:
        return {"error": "Failed to remove task"}
    return {"status": "ok", "task_id": task_id}


# ── Resources ──────────────────────────────────────────────


@mcp.resource("todo://projects")
def resource_projects() -> str:
    """List of all projects."""
    manager = _get_manager()
    projects = manager.list_projects()
    lines = [p["name"] for p in projects]
    return "\n".join(lines) if lines else "(no projects)"


@mcp.resource("todo://tasks/{project}")
def resource_tasks(project: str) -> str:
    """Raw contents of the .todo file for a project."""
    manager = _get_manager()
    path = manager.get_project_path(project)
    if not path.exists():
        return f"Project '{project}' not found"
    return path.read_text()


# ── Entry point ────────────────────────────────────────────


def run_server():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
