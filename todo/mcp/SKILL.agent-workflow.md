# Todo Agent Workflow

You are a coding agent with access to a todo task management system. A `TODO.md` file in the project root is a symlink to a managed task list. Your job is to pick tasks, do the work, and mark them done.

## Setup

You have access to todo MCP tools:

- **`list_tasks(project)`** — List all tasks with task_id, text, checked state, indent level
- **`toggle_task(project, task_id)`** — Toggle a task between pending and done
- **`add_task(project, text, parent_task_id?)`** — Add a new task or subtask
- **`edit_task(project, task_id, new_text)`** — Update a task's text
- **`remove_task(project, task_id)`** — Delete a task

If MCP tools are not available, use the CLI instead:

```bash
todo ls -p <project>           # List tasks
todo check <n> -p <project>    # Mark task done
todo add "<text>" -p <project> # Add a task
```

## The Work Loop

### 1. Read the task list

Call `list_tasks("<project>")` (or read `TODO.md` directly). Identify all unchecked tasks.

### 2. Pick the next task

Choose the next unchecked task to work on. Use your judgment:

- Prefer tasks whose dependencies (parent or sibling tasks above them) are already done.
- Prefer tasks earlier in the list when there's no clear dependency reason to skip ahead.
- If a task has unchecked subtasks, complete the subtasks first, then mark the parent done.

### 3. Do the work

Implement the task. Follow normal software engineering practices:

- Read relevant code before making changes.
- Make small, focused changes.
- Run tests if available.
- Commit your work with a descriptive message referencing the task:
  ```
  git add <changed files>
  git commit -m "<task text>"
  ```

### 4. Mark the task done

After the work is complete and committed:

```
toggle_task("<project>", "<task_id>")
```

Or via CLI: `todo check <n> -p <project>`

### 5. Repeat or stop

- **If there are more unchecked tasks**: go back to step 1.
- **If your context is getting long**: hand off to a new thread/session with a note like "Continue working through TODO.md tasks for project X. Tasks 1-4 are done."
- **If a task is blocked or unclear**: stop and report what's blocking you. Do not guess.
- **If all tasks are done**: report completion.

## Rules

- **One task at a time.** Complete and commit each task before starting the next.
- **Never skip a failing task silently.** If you can't complete a task, say so.
- **Don't edit TODO.md directly.** Always use MCP tools or the CLI to modify tasks.
- **Re-read the task list after completing each task.** Tasks may have been added or changed by a human or another agent.
- **Stay scoped to the project.** Only work on tasks in the linked project.

## Context Management

If you are working through many tasks and your context window is filling up:

- Finish and commit the current task.
- Mark it done.
- Hand off to a fresh session with a summary: which project, which tasks are done, what's next.

This ensures each task gets a clean, focused context.
