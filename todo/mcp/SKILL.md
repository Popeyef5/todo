# Todo Task Management

You have access to a todo task management system via MCP tools. Use these tools to create, manage, and track tasks across projects.

## Available Tools

- **`list_projects`** — List all projects with pending/done counts
- **`list_tasks(project)`** — List all tasks in a project with their task_id, text, checked state, and indent level
- **`add_task(project, text, parent_task_id?)`** — Add a new task. Use `parent_task_id` to create subtasks
- **`toggle_task(project, task_id)`** — Toggle a task between pending and done
- **`edit_task(project, task_id, new_text)`** — Update a task's text
- **`remove_task(project, task_id)`** — Delete a task and its subtasks

## Writing Good Tasks

When creating tasks, follow these principles:

1. **Use imperative verbs** — Start each task with an action: "Add", "Create", "Implement", "Fix", "Update", "Remove", "Write", "Configure"
2. **Be specific and atomic** — Each task should be completable in a single focused session. Break large work into subtasks.
3. **Include context** — Mention the file, module, or component: "Add validation to POST /users endpoint" not "Add validation"
4. **Order by dependency** — Add tasks in the order they should be executed. Earlier tasks should not depend on later ones.
5. **Use subtasks for multi-step work** — Use `parent_task_id` to nest implementation details under a parent task.

### Example: Planning a feature

Instead of:
```
- [ ] Add authentication
```

Do this:
```
- [ ] Implement user authentication
    - [ ] Add bcrypt to requirements.txt
    - [ ] Create User model with email and password_hash fields in models/user.py
    - [ ] Implement POST /register endpoint with email validation
    - [ ] Implement POST /login endpoint returning JWT token
    - [ ] Add auth middleware to verify JWT on protected routes
    - [ ] Write tests for register, login, and middleware
```

To create this structure with MCP tools:
1. `add_task("myproject", "Implement user authentication")` → returns the parent
2. `list_tasks("myproject")` → get the parent's `task_id`
3. `add_task("myproject", "Add bcrypt to requirements.txt", parent_task_id="<id>")` — repeat for each subtask

## Rules

- **Always use MCP tools to modify tasks.** Never edit `.todo` files directly.
- **Read before writing** — Call `list_tasks` before modifying to get current task_ids and state.
- **Mark tasks done as you complete them** — Use `toggle_task` after finishing work.
- Tasks are stored as markdown checkboxes (`- [ ]` / `- [x]`) and are visible in the project's `TODO.md` file.

## Resources

- `todo://projects` — Quick list of all project names
- `todo://tasks/{project}` — Raw contents of a project's task file
