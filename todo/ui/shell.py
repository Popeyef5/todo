"""
Interactive shell - the main REPL for Todo
"""

import io
import os
import sys
import shlex
import contextlib
from pathlib import Path
from typing import List, Optional

from todo.core.manager import TodoManager
from todo.sync.auth import resolve_token, _token_from_cli, clear_token_cache
from todo.sync.main_sync import MainSync
from todo.sync.background import BackgroundSync
from todo.sync.providers import (
    GitHubProvider, GitLabProvider, parse_remote_url,
)
from todo.ui import render
from todo.ui.render import S
from todo.ui.tasks import (
    TaskRef, parse_tasks_from_file, toggle_task_in_file,
    add_task_to_file, edit_task_in_file, remove_task_from_file,
    get_children_ids,
)
from todo.ui.themes import get_theme, set_theme, list_themes, load_custom_themes


@contextlib.contextmanager
def _quiet():
    """Suppress stdout (sync debug prints) temporarily"""
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old


class TodoShell:
    """Interactive command shell for Todo

    Two-level hierarchy:
    - Global view: all tasks from all projects (default when no project scope)
    - Project view: all tasks from one project (one .todo file per project)

    Edits modify the source .todo files directly in ~/.todo/data/,
    then sync propagates changes across repos.
    """

    def __init__(self, manager: TodoManager, initial_target: str = None):
        self.manager = manager
        self.current_project = None  # Name of current project scope
        self.tasks: List[TaskRef] = []  # Numbered task results
        self.dirty = False
        self.stage_view = False
        self.hide_done = False
        self._bg_sync = None  # BackgroundSync instance

        # Load custom themes from ~/.todo/themes/, then apply saved preference
        load_custom_themes(manager.themes_dir)
        saved_theme = manager.config.get("theme")
        if saved_theme:
            set_theme(saved_theme)

        # Try to set initial scope
        if initial_target:
            self._cmd_use([initial_target])

        # Setup readline if available
        self._setup_readline()

    def _setup_readline(self):
        """Setup readline for history and completion"""
        try:
            import readline
            history_file = self.manager.home_dir / ".shell_history"
            try:
                readline.read_history_file(str(history_file))
            except FileNotFoundError:
                pass
            readline.set_history_length(500)

            import atexit
            atexit.register(readline.write_history_file, str(history_file))

            # Tab completion
            commands = [
                'help', 'projects', 'use', 'ls', 'show', 'add', 'addc',
                'toggle', 'check', 'uncheck', 'edit', 'rm', 'project', 'find', 'hide', 'group',
                'setup', 'sync', 'push', 'pull', 'config', 'nuke', 'link',
                'unlink', 'status', 'theme', 'stage', 'unstage', 'staged',
                'clear', 'quit', 'q', 'exit',
            ]

            def completer(text, state):
                options = [c for c in commands if c.startswith(text)]
                if state < len(options):
                    return options[state]
                return None

            readline.set_completer(completer)
            readline.parse_and_bind("tab: complete")
        except ImportError:
            pass

    def run(self):
        """Main REPL loop"""
        print(render.banner())

        # Initial sync + start background checker
        auto_sync = self.manager.config.get("auto_sync_on_edit", True)
        if auto_sync:
            print(render.dim("  syncing..."), end="", flush=True)
            sync_result = self._do_sync_quiet()
            sys.stdout = sys.__stdout__
            self._print_sync_result(sync_result)
            self._start_background_sync()

        # Show initial view
        self._refresh_tasks()
        if self.tasks:
            self._print_tasks()

        while True:
            try:
                prompt = render.prompt_str(self.current_project)
                raw = input(prompt)
            except (EOFError, KeyboardInterrupt):
                print()
                self._quit()
                return

            line = raw.strip()
            if not line:
                continue

            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()

            cmd = parts[0].lower()
            args = parts[1:]

            handler = {
                'help': self._cmd_help,
                '?': self._cmd_help,
                'projects': self._cmd_projects,
                'use': self._cmd_use,
                'ls': self._cmd_ls,
                'show': self._cmd_show,
                'add': self._cmd_add,
                'toggle': self._cmd_toggle,
                't': self._cmd_toggle,
                'find': self._cmd_find,
                'hide': self._cmd_hide,
                'check': self._cmd_check,
                'uncheck': self._cmd_uncheck,
                'edit': self._cmd_edit,
                'e': self._cmd_edit,
                'rm': self._cmd_rm,
                'project': self._cmd_project,
                'addc': self._cmd_addc,
                'group': self._cmd_group,
                'setup': self._cmd_setup,
                'sync': self._cmd_sync,
                'push': self._cmd_push,
                'pull': self._cmd_pull,
                'config': self._cmd_config,
                'nuke': self._cmd_nuke,
                'link': self._cmd_link,
                'unlink': self._cmd_unlink,
                'stage': self._cmd_stage,
                'unstage': self._cmd_unstage,
                'staged': self._cmd_staged,
                'status': self._cmd_status,
                'theme': self._cmd_theme,
                'clear': self._cmd_clear,
                'quit': self._cmd_quit,
                'q': self._cmd_quit,
                'exit': self._cmd_quit,
            }.get(cmd)

            if handler:
                try:
                    handler(args)
                except Exception as exc:
                    print(render.error(str(exc)))
            else:
                # Try numeric input as toggle shorthand
                try:
                    n = int(cmd)
                    self._cmd_toggle([str(n)])
                except ValueError:
                    print(render.error(f"Unknown command: {cmd}"))
                    print(render.dim("  Type 'help' for available commands"))

            # Check for pending background sync
            self._check_pending_sync()

    # ── Task management ───────────────────────────────────────────────

    def _propagate(self):
        """Sync changes across repos. Called after every mutation."""
        sync_result = self._do_sync_quiet()
        if sync_result and sync_result.get("conflicts"):
            for c in sync_result["conflicts"]:
                print(render.warn(c))
        self.dirty = False

    def _refresh_tasks(self):
        """Reload tasks from files"""
        self.tasks = []
        if self.current_project:
            # Project view: tasks from this project's .todo file
            path = self.manager.get_project_path(self.current_project)
            if path and path.exists():
                self.tasks = parse_tasks_from_file(path, self.current_project)
        else:
            # Global view: all tasks from all projects, sorted so parents come before children
            project_paths = sorted(self.manager.get_all_project_paths(), key=lambda x: x[0])
            for name, path in project_paths:
                tasks = parse_tasks_from_file(path, name)
                self.tasks.extend(tasks)
        if self.stage_view:
            staged_ids = self.manager.load_staged_ids()
            self.tasks = [t for t in self.tasks if t.task_id in staged_ids]
        if self.hide_done:
            self.tasks = [t for t in self.tasks if not t.checked]

    def _print_tasks(self, tasks: List[TaskRef] = None):
        """Print numbered task list"""
        items = tasks if tasks is not None else self.tasks
        if not items:
            print(render.dim("  No tasks found"))
            return

        # Group by project with nested hierarchy
        current_project = None
        seen_projects = set()
        lines = []

        for i, task in enumerate(items, 1):
            if task.project_name != current_project:
                current_project = task.project_name
                if current_project not in seen_projects:
                    seen_projects.add(current_project)
                    # Emit ancestor headers if not yet seen
                    parts = current_project.split("/")
                    for j in range(1, len(parts)):
                        ancestor = "/".join(parts[:j])
                        if ancestor not in seen_projects:
                            seen_projects.add(ancestor)
                            depth = ancestor.count("/")
                            display_name = ancestor.rsplit("/", 1)[-1] if "/" in ancestor else ancestor
                            header_indent = "  " + "    " * depth
                            if lines:
                                lines.append("")
                            lines.append(f"{header_indent}{render.color(display_name, S.BLUE, S.BOLD)}")
                    depth = current_project.count("/")
                    display_name = current_project.rsplit("/", 1)[-1] if "/" in current_project else current_project
                    header_indent = "  " + "    " * depth
                    if lines:
                        lines.append("")
                    lines.append(f"{header_indent}{render.color(display_name, S.BLUE, S.BOLD)}")

            lines.append(render.task_line(i, task.checked, task.text))

        scope = self.current_project or "all projects"
        unchecked = sum(1 for t in items if not t.checked)
        checked = sum(1 for t in items if t.checked)
        summary = f"{unchecked} pending, {checked} done"
        title = f"{scope} — {summary}"

        print(render.box(title, lines))

    def _get_task(self, n: int) -> Optional[TaskRef]:
        """Get task by 1-based index"""
        if n < 1 or n > len(self.tasks):
            print(render.error(f"Invalid task number: {n} (valid: 1-{len(self.tasks)})"))
            return None
        return self.tasks[n - 1]

    # ── Command handlers ──────────────────────────────────────────────

    def _cmd_help(self, args):
        lines = [
            "",
            f"  {render.color('Navigation', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('projects', S.BRIGHT_CYAN)}           List all projects",
            f"    {render.color('use', S.BRIGHT_CYAN)} {render.color('<project>', S.DIM)}     Switch to a project scope",
            f"    {render.color('use', S.BRIGHT_CYAN)}                 Switch to global scope (all projects)",
            "",
            f"  {render.color('Viewing', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('ls', S.BRIGHT_CYAN)}                  List tasks in current scope",
            f"    {render.color('find', S.BRIGHT_CYAN)} {render.color('<text>', S.DIM)}        Search tasks by text",
            f"    {render.color('hide', S.BRIGHT_CYAN)}                Toggle hiding completed tasks",
            f"    {render.color('show', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}           Show details of task #n",
            f"    {render.color('status', S.BRIGHT_CYAN)}              Show sync and project status",
            "",
            f"  {render.color('Editing', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('add', S.BRIGHT_CYAN)} {render.color('<text>', S.DIM)}         Add a new task to current project",
            f"    {render.color('addc', S.BRIGHT_CYAN)} {render.color('<n> <text>', S.DIM)}    Add a child task under task #n",
            f"    {render.color('toggle', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}  /  {render.color('t', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}  Toggle task checkbox",
            f"    {render.color('<n>', S.BRIGHT_CYAN)}                  Toggle task #n (shorthand)",
            f"    {render.color('check', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}          Mark task as done",
            f"    {render.color('uncheck', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}        Mark task as not done",
            f"    {render.color('edit', S.BRIGHT_CYAN)} {render.color('<n> <text>', S.DIM)}    Edit task text",
            f"    {render.color('rm', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}             Remove a task",
            "",
            f"  {render.color('Staging', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('stage', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}           Stage task(s) for focused work",
            f"    {render.color('stage', S.BRIGHT_CYAN)}                Toggle staging view on/off",
            f"    {render.color('unstage', S.BRIGHT_CYAN)} {render.color('<n>', S.DIM)}         Unstage task(s)",
            f"    {render.color('staged', S.BRIGHT_CYAN)}               Show staged tasks",
            "",
            f"  {render.color('Projects', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('project new', S.BRIGHT_CYAN)} {render.color('<name>', S.DIM)}      Create a new project",
            f"    {render.color('project delete', S.BRIGHT_CYAN)} {render.color('<name>', S.DIM)}   Delete a project",
            f"    {render.color('link', S.BRIGHT_CYAN)} {render.color('<project> [path]', S.DIM)}    Link TODO.md in directory",
            f"    {render.color('unlink', S.BRIGHT_CYAN)} {render.color('<project> [path]', S.DIM)}  Unlink TODO.md from directory",
            "",
            f"  {render.color('Groups', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('group new', S.BRIGHT_CYAN)} {render.color('<name>', S.DIM)}       Create a new group",
            f"    {render.color('group add', S.BRIGHT_CYAN)} {render.color('<project> <group>', S.DIM)}  Add project to group",
            f"    {render.color('group sync', S.BRIGHT_CYAN)} {render.color('<group>', S.DIM)}     Setup sync for a group",
            f"    {render.color('group invite', S.BRIGHT_CYAN)} {render.color('<group> <user>', S.DIM)}  Invite user to group",
            f"    {render.color('group join', S.BRIGHT_CYAN)} {render.color('<group> <url>', S.DIM)}   Join a group via URL",
            f"    {render.color('group list', S.BRIGHT_CYAN)}             List all groups",
            "",
            f"  {render.color('Sync', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('setup', S.BRIGHT_CYAN)}               Setup multi-device sync",
            f"    {render.color('sync', S.BRIGHT_CYAN)}                Sync all repos",
            f"    {render.color('push', S.BRIGHT_CYAN)}                Sync (push changes)",
            f"    {render.color('pull', S.BRIGHT_CYAN)}                Sync (pull changes)",
            "",
            f"  {render.color('Other', S.BOLD, S.BRIGHT_WHITE)}",
            f"    {render.color('config', S.BRIGHT_CYAN)}              View/set configuration",
            f"    {render.color('nuke', S.BRIGHT_CYAN)}                Delete all todo data",
            f"    {render.color('theme', S.BRIGHT_CYAN)} {render.color('[name]', S.DIM)}       View/switch UI theme",
            f"    {render.color('clear', S.BRIGHT_CYAN)}               Clear screen",
            f"    {render.color('q', S.BRIGHT_CYAN)} / {render.color('quit', S.BRIGHT_CYAN)} / {render.color('exit', S.BRIGHT_CYAN)}     Exit",
            "",
        ]
        print("\n".join(lines))

    def _cmd_projects(self, args):
        project_list = self.manager.list_projects()
        if not project_list:
            print(render.dim("  No projects found. Use 'project new <name>' to create one."))
            return

        projects = []
        for p in project_list:
            path = p["path"]
            # Count tasks from the file
            try:
                tasks = parse_tasks_from_file(path, p["name"])
                todo_count = len(tasks)
            except Exception:
                todo_count = 0
            shared = p.get("shared_in", [])
            ptype = f"shared: {', '.join(shared)}" if shared else "local"
            projects.append({
                "name": p["name"],
                "todo_count": todo_count,
                "type": ptype,
            })

        print(render.header("Projects"))
        print(render.project_tree(projects, self.current_project))
        print()

    def _cmd_use(self, args):
        if not args:
            self.current_project = None
            print(render.info("Switched to global scope (all projects)"))
            self._refresh_tasks()
            self._print_tasks()
            return

        name = " ".join(args)
        path = self.manager.get_project_path(name)
        if not path:
            print(render.error(f"Project not found: {name}"))
            return

        self.current_project = name
        print(render.info(f"Switched to project: {render.color(self.current_project, S.BOLD)}"))
        self._refresh_tasks()
        self._print_tasks()

    def _cmd_ls(self, args):
        self._refresh_tasks()
        self._print_tasks()

    def _cmd_find(self, args):
        if not args:
            print(render.error("Usage: find <text>"))
            return
        query = ' '.join(args).lower()
        self._refresh_tasks()
        matches = [t for t in self.tasks if query in t.text.lower()]
        if not matches:
            print(render.dim(f"  No tasks matching '{' '.join(args)}'"))
            return
        self._print_tasks(matches)

    def _cmd_hide(self, args):
        self.hide_done = not self.hide_done
        self._refresh_tasks()
        if self.hide_done:
            print(render.success("Hiding completed tasks"))
        else:
            print(render.success("Showing all tasks"))
        self._print_tasks()

    def _cmd_show(self, args):
        if not args:
            print(render.error("Usage: show <n>"))
            return
        try:
            n = int(args[0])
        except ValueError:
            print(render.error("Expected a number"))
            return

        task = self._get_task(n)
        if not task:
            return

        checkbox = render.color("[x]", S.GREEN) if task.checked else render.color("[ ]", S.YELLOW)
        lines = [
            f"  Task #{n}",
            f"  {checkbox} {task.text}",
            f"  {render.color('Project:', S.DIM)} {task.project_name}",
            f"  {render.color('File:', S.DIM)}    {task.todo_path}",
            f"  {render.color('Line:', S.DIM)}    {task.line_no + 1}",
        ]
        print("\n".join(lines))

    def _cmd_add(self, args):
        if not args:
            print(render.error("Usage: add <task text>"))
            return

        text = " ".join(args)

        if not self.current_project:
            print(render.error("Select a project first with 'use <project>'"))
            return

        target_file = self.manager.get_project_path(self.current_project)
        if not target_file:
            print(render.error(f"Project not found: {self.current_project}"))
            return

        add_task_to_file(target_file, text)
        self._propagate()
        self._refresh_tasks()
        print(render.success(f"Added: {text}"))

    def _cmd_toggle(self, args):
        if not args:
            print(render.error("Usage: toggle <n> [n2 n3 ...]"))
            return

        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                print(render.error(f"Expected a number, got: {arg}"))
                continue

            task = self._get_task(n)
            if not task:
                continue

            new_state = toggle_task_in_file(task.todo_path, task.line_no)
            state_str = render.color("done", S.GREEN) if new_state else render.color("pending", S.YELLOW)
            print(render.success(f"#{n} → {state_str}: {task.text}"))

        self._propagate()
        self._refresh_tasks()

    def _cmd_check(self, args):
        if not args:
            print(render.error("Usage: check <n>"))
            return
        changed = False
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                print(render.error(f"Expected a number, got: {arg}"))
                continue
            task = self._get_task(n)
            if not task:
                continue
            if not task.checked:
                toggle_task_in_file(task.todo_path, task.line_no)
                changed = True
                print(render.success(f"#{n} → {render.color('done', S.GREEN)}: {task.text}"))
            else:
                print(render.dim(f"  #{n} already done"))
        if changed:
            self._propagate()
        self._refresh_tasks()

    def _cmd_uncheck(self, args):
        if not args:
            print(render.error("Usage: uncheck <n>"))
            return
        changed = False
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                print(render.error(f"Expected a number, got: {arg}"))
                continue
            task = self._get_task(n)
            if not task:
                continue
            if task.checked:
                toggle_task_in_file(task.todo_path, task.line_no)
                changed = True
                print(render.success(f"#{n} → {render.color('pending', S.YELLOW)}: {task.text}"))
            else:
                print(render.dim(f"  #{n} already pending"))
        if changed:
            self._propagate()
        self._refresh_tasks()

    def _cmd_stage(self, args):
        if not args:
            # Toggle stage view
            self.stage_view = not self.stage_view
            self._refresh_tasks()
            if self.stage_view:
                print(render.success("Switched to staging view"))
                self._print_tasks()
            else:
                print(render.success("Switched to normal view"))
                self._print_tasks()
            return
        # Stage specific tasks by number or project name
        staged_ids = self.manager.load_staged_ids()
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                self._stage_project_by_name(arg, staged_ids, stage=True)
                continue
            task = self._get_task(n)
            if not task:
                continue
            if not task.task_id:
                print(render.error(f"Task #{n} has no ID"))
                continue
            if task.task_id in staged_ids:
                print(render.dim(f"  #{n} already staged"))
                continue
            staged_ids.add(task.task_id)
            for cid in get_children_ids(self.tasks, task):
                staged_ids.add(cid)
            print(render.success(f"Staged #{n}: {task.text}"))
        self.manager.save_staged_ids(staged_ids)

    def _cmd_unstage(self, args):
        if not args:
            print(render.error("Usage: unstage <n|project> [...]"))
            return
        staged_ids = self.manager.load_staged_ids()
        for arg in args:
            try:
                n = int(arg)
            except ValueError:
                self._stage_project_by_name(arg, staged_ids, stage=False)
                continue
            task = self._get_task(n)
            if not task:
                continue
            if task.task_id not in staged_ids:
                print(render.dim(f"  #{n} is not staged"))
                continue
            staged_ids.discard(task.task_id)
            print(render.success(f"Unstaged #{n}: {task.text}"))
        self.manager.save_staged_ids(staged_ids)
        if self.stage_view:
            self._refresh_tasks()
            self._print_tasks()

    def _stage_project_by_name(self, name: str, staged_ids: set, stage: bool):
        """Stage or unstage all tasks in a project by name."""
        project_tasks = [
            t for t in self.tasks
            if t.project_name == name or t.project_name.startswith(name + "/")
        ]
        if not project_tasks:
            print(render.error(f"No project matching: {name}"))
            return
        task_ids = {t.task_id for t in project_tasks if t.task_id}
        if not task_ids:
            print(render.error(f"Tasks in {name} have no IDs"))
            return
        if stage:
            staged_ids |= task_ids
            print(render.success(f"Staged {len(task_ids)} tasks from {name}"))
        else:
            staged_ids -= task_ids
            print(render.success(f"Unstaged {len(task_ids)} tasks from {name}"))

    def _cmd_staged(self, args):
        # Show staged view
        self.stage_view = True
        self._refresh_tasks()
        if self.tasks:
            self._print_tasks()
        else:
            print(render.dim("  No staged tasks. Use 'stage <n>' to stage tasks."))
        self.stage_view = False
        self._refresh_tasks()

    def _cmd_edit(self, args):
        if len(args) < 2:
            print(render.error("Usage: edit <n> <new text>"))
            return
        try:
            n = int(args[0])
        except ValueError:
            print(render.error("Expected a number"))
            return

        task = self._get_task(n)
        if not task:
            return

        new_text = " ".join(args[1:])
        if edit_task_in_file(task.todo_path, task.line_no, new_text):
            print(render.success(f"#{n} updated: {new_text}"))
            self._propagate()
            self._refresh_tasks()
        else:
            print(render.error("Failed to edit task"))

    def _cmd_rm(self, args):
        if not args:
            print(render.error("Usage: rm <n>"))
            return
        try:
            n = int(args[0])
        except ValueError:
            print(render.error("Expected a number"))
            return

        task = self._get_task(n)
        if not task:
            return

        if remove_task_from_file(task.todo_path, task.line_no):
            print(render.success(f"Removed: {task.text}"))
            self._propagate()
            self._refresh_tasks()
        else:
            print(render.error("Failed to remove task"))

    def _cmd_project(self, args):
        if not args:
            print(render.error("Usage: project <new|delete> ..."))
            return
        sub = args[0].lower()
        if sub == 'new':
            if len(args) < 2:
                print(render.error("Usage: project new <name>"))
                return
            name = args[1]
            self.manager.create_project(name)
            print(render.success(f"Created project: {name}"))
            self.current_project = name
            self._refresh_tasks()
        elif sub == 'delete':
            if len(args) < 2:
                print(render.error("Usage: project delete <name>"))
                return
            name = args[1]
            confirm = self._prompt(f"  Delete project '{name}' and all its tasks? [y/N]")
            if confirm.lower() != 'y':
                print(render.dim("  (cancelled)"))
                return
            if self.manager.remove_project(name):
                print(render.success(f"Deleted project: {name}"))
                if self.current_project == name:
                    self.current_project = None
                self._refresh_tasks()
            else:
                print(render.error(f"Project '{name}' not found"))
        else:
            print(render.error(f"Unknown project action: {sub}"))

    def _cmd_addc(self, args):
        if len(args) < 2:
            print(render.error("Usage: addc <n> <task text>"))
            return
        try:
            n = int(args[0])
        except ValueError:
            print(render.error(f"Expected a number, got: {args[0]}"))
            return
        parent = self._get_task(n)
        if not parent:
            return
        text = " ".join(args[1:])
        child_indent = parent.indent + "    "
        add_task_to_file(parent.todo_path, text, indent=child_indent, after_line=parent.line_no)
        self._propagate()
        self._refresh_tasks()
        print(render.success(f"Added under #{n}: {text}"))

    def _cmd_group(self, args):
        """Handle group sub-commands: new, add, sync, invite, join, list"""
        if not args:
            print(render.error("Usage: group <new|add|sync|invite|join|list> ..."))
            return

        sub = args[0].lower()

        if sub == 'new':
            if len(args) < 2:
                print(render.error("Usage: group new <name>"))
                return
            name = args[1]
            try:
                self.manager.create_group(name)
                print(render.success(f"Created group: {name}"))
            except ValueError as e:
                print(render.error(str(e)))

        elif sub == 'add':
            if len(args) < 3:
                print(render.error("Usage: group add <project> <group>"))
                return
            project_name, group_name = args[1], args[2]
            try:
                self.manager.add_project_to_group(project_name, group_name)
                print(render.success(f"Added '{project_name}' to group '{group_name}'"))
            except ValueError as e:
                print(render.error(str(e)))

        elif sub == 'sync':
            if len(args) < 2:
                print(render.error("Usage: group sync <group>"))
                return
            group_name = args[1]
            registry = self.manager.load_registry()
            if group_name not in registry.get("groups", {}):
                print(render.error(f"Group '{group_name}' not found"))
                return
            existing_remote = registry["groups"][group_name].get("remote")
            if existing_remote:
                print(render.info(f"Group '{group_name}' already has remote: {existing_remote}"))
                answer = self._prompt("  Reconfigure? [y/N]")
                if answer.lower() != "y":
                    return
            self._cmd_setup(args[1:])

        elif sub == 'invite':
            if len(args) < 3:
                print(render.error("Usage: group invite <group> <username>"))
                return
            group_name, username = args[1], args[2]
            try:
                print(render.dim(f"  Inviting '{username}' to '{group_name}'..."))
                if self.manager.invite_to_group(group_name, username):
                    print(render.success(f"Invited '{username}' as collaborator on '{group_name}'"))
                else:
                    print(render.error(f"Failed to invite '{username}'. Check the username and your permissions."))
            except ValueError as e:
                print(render.error(str(e)))

        elif sub == 'join':
            if len(args) < 3:
                print(render.error("Usage: group join <group> <url>"))
                return
            group_name, remote_url = args[1], args[2]
            try:
                print(render.dim(f"  Joining group '{group_name}'..."))
                if self.manager.join_group(group_name, remote_url):
                    print(render.success(f"Joined group '{group_name}'"))
                    self._refresh_tasks()
                else:
                    print(render.error(f"Failed to join '{group_name}'. Check the URL and your access."))
            except ValueError as e:
                print(render.error(str(e)))

        elif sub == 'list':
            registry = self.manager.load_registry()
            groups = registry.get("groups", {})
            if not groups:
                print(render.dim("  No groups. Use 'group new <name>' to create one."))
                return
            print(render.header("Groups"))
            for name, info in groups.items():
                projects = info.get("projects", [])
                pcount = len(projects)
                has_remote = bool(info.get("remote"))
                remote = info.get("remote") or "no remote"
                sync_icon = render.color("🔗", S.GREEN) if has_remote else render.color("📝", S.DIM)
                proj_str = ", ".join(projects) if projects else "empty"
                print(f"  {sync_icon} {render.color(name, S.BOLD)} ({pcount} projects) [{proj_str}] ({remote})")
            print()

        else:
            print(render.error(f"Unknown group command: {sub}"))
            print(render.dim("  Usage: group <new|add|sync|invite|join|list>"))

    def _cmd_config(self, args):
        if not args:
            print(render.header("Configuration"))
            for key, value in self.manager.config.config.items():
                display = value
                if isinstance(value, str) and "token" in key.lower() and value:
                    display = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
                print(f"  {render.color(key, S.BRIGHT_CYAN)}: {display}")
            print()
            return
        key = args[0]
        if len(args) < 2:
            value = self.manager.config.get(key)
            if value is not None:
                display = value
                if isinstance(value, str) and "token" in key.lower() and value:
                    display = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
                print(f"  {render.color(key, S.BRIGHT_CYAN)}: {display}")
            else:
                print(render.dim(f"  {key} is not set"))
            return
        value_str = " ".join(args[1:])
        if value_str.lower() == "true":
            value_str = True
        elif value_str.lower() == "false":
            value_str = False
        elif value_str.lower() == "null" or value_str.lower() == "none":
            value_str = None
        else:
            try:
                value_str = int(value_str)
            except ValueError:
                pass
        self.manager.config.set(key, value_str)
        print(render.success(f"Set {key} = {value_str}"))

    def _cmd_nuke(self, args):
        if self.manager.nuke_all():
            print(render.success("All todo data has been deleted."))
        else:
            print(render.dim("  Cancelled."))

    def _cmd_link(self, args):
        if not args:
            print(render.error("Usage: link <project> [path]"))
            return
        project_name = args[0]
        target_dir = Path(args[1]) if len(args) > 1 else None
        try:
            symlink = self.manager.link_project(project_name, target_dir)
            print(render.success(f"Linked: {symlink}"))
        except ValueError as e:
            print(render.error(str(e)))

    def _cmd_unlink(self, args):
        if not args:
            print(render.error("Usage: unlink <project> [path]"))
            return
        project_name = args[0]
        target_dir = Path(args[1]) if len(args) > 1 else None
        try:
            if self.manager.unlink_project(project_name, target_dir):
                print(render.success(f"Unlinked TODO.md for '{project_name}'"))
            else:
                print(render.dim("  No symlink found to remove."))
        except ValueError as e:
            print(render.error(str(e)))

    def _cmd_setup(self, args):
        """Interactive sync setup wizard."""
        main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if main_sync.is_sync_enabled():
            status = main_sync.get_sync_status()
            print(render.info(f"Sync is already configured: {status.get('remote_url')}"))
            answer = self._prompt("Reconfigure? [y/N]")
            if answer.lower() != "y":
                return

        print()
        print(render.color("  Multi-device sync setup", S.BOLD, S.BRIGHT_CYAN))
        print(render.dim("  Sync your todos across devices via a private git repo.\n"))

        # ── Step 1: Provider ──
        print(render.color("  Provider", S.BOLD, S.BRIGHT_WHITE))
        print(f"    {render.color('1', S.BRIGHT_CYAN)}) GitHub")
        print(f"    {render.color('2', S.BRIGHT_CYAN)}) GitLab")
        print(f"    {render.color('3', S.BRIGHT_CYAN)}) Other git host")
        choice = self._prompt("  Choose [1/2/3]", default="1")
        provider = {"1": "github", "2": "gitlab", "3": "other"}.get(choice, "github")
        print()

        # ── Step 2: Auth ──
        token = None
        username = None

        if provider in ("github", "gitlab"):
            token, username = self._setup_auth(provider)
            if not token:
                print(render.error("No token configured. Sync setup aborted."))
                return
            print()

        # ── Step 3: Repo URL ──
        print(render.color("  Repository", S.BOLD, S.BRIGHT_WHITE))

        if provider in ("github", "gitlab") and token and username:
            print(f"    {render.color('1', S.BRIGHT_CYAN)}) Create a new private repo")
            print(f"    {render.color('2', S.BRIGHT_CYAN)}) Use an existing repo URL")
            repo_choice = self._prompt("  Choose [1/2]", default="1")

            if repo_choice == "1":
                remote_url = self._setup_create_repo(provider, token, username)
                if not remote_url:
                    return
            else:
                remote_url = self._prompt("  Repo URL")
                if not remote_url:
                    print(render.error("No URL provided."))
                    return
        else:
            remote_url = self._prompt("  Repo URL (HTTPS or SSH)")
            if not remote_url:
                print(render.error("No URL provided."))
                return

        print()

        # ── Step 4: Apply ──
        print(render.dim("  Configuring sync..."))
        if self.manager.sync_setup(remote_url):
            print(render.success(f"Sync configured: {remote_url}"))
            self._start_background_sync()
        else:
            print(render.error("Setup failed. Check your URL and auth."))

    def _setup_auth(self, provider: str):
        """Handle auth for a provider. Returns (token, username) or (None, None)."""
        label = "GitHub" if provider == "github" else "GitLab"
        cli_name = "gh" if provider == "github" else "glab"
        config_key = "github_token" if provider == "github" else "gitlab_token"

        # Try existing token from all sources
        token = resolve_token(provider, self.manager.config)
        if token:
            # Validate it
            prov = self._make_provider(provider, token)
            username = prov.validate_token(token) if prov else None
            if username:
                print(render.success(f"Authenticated as {render.color(username, S.BOLD)} ({label})"))
                return token, username
            else:
                print(render.warn(f"Existing {label} token is invalid or expired."))
                clear_token_cache()

        # Try CLI detection
        cli_token = _token_from_cli(provider)
        if cli_token:
            prov = self._make_provider(provider, cli_token)
            username = prov.validate_token(cli_token) if prov else None
            if username:
                print(render.success(
                    f"Authenticated as {render.color(username, S.BOLD)} "
                    f"(via {render.color(cli_name, S.BRIGHT_CYAN)} CLI)"
                ))
                self.manager.config.set(config_key, cli_token)
                return cli_token, username

        # Manual token entry
        print(render.dim(f"  No {label} auth found."))
        if provider == "github":
            print(render.dim("  Create a token at: https://github.com/settings/tokens/new"))
            print(render.dim("  Required scope: 'repo' (or fine-grained: Contents read/write)"))
        else:
            print(render.dim("  Create a token at: https://gitlab.com/-/user_settings/personal_access_tokens"))
            print(render.dim("  Required scope: api"))
        print()
        token = self._prompt(f"  {label} token")
        if not token:
            return None, None

        # Validate
        prov = self._make_provider(provider, token)
        username = prov.validate_token(token) if prov else None
        if username:
            print(render.success(f"Authenticated as {render.color(username, S.BOLD)}"))
            self.manager.config.set(config_key, token)
            return token, username
        else:
            print(render.error("Token validation failed."))
            save_anyway = self._prompt("  Save token anyway? [y/N]")
            if save_anyway.lower() == "y":
                self.manager.config.set(config_key, token)
                return token, None
            return None, None

    def _setup_create_repo(self, provider: str, token: str, username: str):
        """Create a remote repo via API. Returns clone URL or None."""
        default_name = ".todos"
        name = self._prompt(f"  Repo name [{default_name}]", default=default_name)
        prov = self._make_provider(provider, token)
        if not prov:
            print(render.error("Provider not available."))
            return None
        print(render.dim(f"  Creating private repo '{name}'..."))
        url = prov.create_repo(name, private=True)
        if url:
            print(render.success(f"Created: {url}"))
            return url
        else:
            print(render.error(f"Failed to create repo. It may already exist."))
            # Fallback: construct URL
            label = "GitHub" if provider == "github" else "GitLab"
            fallback_url = prov.get_https_url(username, name)
            if fallback_url:
                use_it = self._prompt(f"  Use {fallback_url}? [Y/n]", default="y")
                if use_it.lower() != "n":
                    return fallback_url
            return None

    def _make_provider(self, provider: str, token: str):
        """Create a provider instance."""
        if provider == "github":
            return GitHubProvider(token)
        elif provider == "gitlab":
            host = self.manager.config.get("gitlab_host", "gitlab.com")
            return GitLabProvider(token, host=host)
        return None

    def _prompt(self, label: str, default: str = "") -> str:
        """Prompt the user for input with an optional default."""
        try:
            if default:
                raw = input(f"{label}: ").strip()
                return raw if raw else default
            return input(f"{label}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default

    def _cmd_sync(self, args):
        # Offer setup if sync isn't configured
        main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if not main_sync.is_sync_enabled():
            print(render.info("Sync is not configured."))
            answer = self._prompt("  Run setup now? [Y/n]", default="y")
            if answer.lower() != "n":
                self._cmd_setup(args)
            return
        print(render.dim("  syncing..."))
        sync_result = self._do_sync_quiet()
        self._print_sync_result(sync_result)
        self._refresh_tasks()

    def _cmd_push(self, args):
        print(render.dim("  syncing..."))
        self._do_sync_quiet()
        print(render.success("Pushed"))
        self.dirty = False

    def _cmd_pull(self, args):
        print(render.dim("  syncing..."))
        sync_result = self._do_sync_quiet()
        self._print_sync_result(sync_result)
        self._refresh_tasks()

    def _cmd_status(self, args):
        project_list = self.manager.list_projects()
        pcount = len(project_list)
        registry = self.manager.load_registry()
        groups = registry.get("groups", {})

        lines = [
            f"  {render.color('Projects:', S.DIM)} {pcount}",
            f"  {render.color('Groups:', S.DIM)}   {len(groups)}",
            f"  {render.color('Scope:', S.DIM)}    {self.current_project or 'global (all)'}",
            f"  {render.color('Tasks:', S.DIM)}    {len(self.tasks)} ({sum(1 for t in self.tasks if not t.checked)} pending)",
            f"  {render.color('Dirty:', S.DIM)}    {'yes' if self.dirty else 'no'}",
        ]

        # Git sync status
        git_dir = self.manager.home_dir / ".git"
        if git_dir.exists():
            lines.append(f"  {render.color('Git sync:', S.DIM)} enabled")
        else:
            lines.append(f"  {render.color('Git sync:', S.DIM)} disabled")

        print(render.box("Status", lines))

    def _cmd_theme(self, args):
        if not args:
            current = get_theme().name
            available = list_themes()
            print(render.info(f"Current theme: {render.color(current, S.BOLD)}"))
            print(render.dim(f"  Available: {', '.join(available)}"))
            print(render.dim(f"  Usage: theme <name>"))
            return
        name = args[0].lower()
        if set_theme(name):
            self.manager.config.set("theme", name)
            print(render.success(f"Theme set to '{name}'"))
        else:
            print(render.error(f"Unknown theme: {name}"))
            print(render.dim(f"  Available: {', '.join(list_themes())}"))

    def _cmd_clear(self, args):
        print("\033[2J\033[H", end="")

    def _cmd_quit(self, args):
        self._quit()
        sys.exit(0)

    def _quit(self):
        """Clean exit with optional sync"""
        self._stop_background_sync()
        if self.dirty:
            auto_sync = self.manager.config.get("auto_sync_on_edit", True)
            if auto_sync:
                print(render.dim("  syncing before exit..."))
                self._do_sync_quiet()
                sys.stdout = sys.__stdout__
                print(render.success("Synced"))
        print(render.dim("  bye 👋"))

    def _do_sync_quiet(self) -> dict:
        """Run sync with stdout suppressed, return result dict."""
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            result = self.manager.sync()
        except Exception:
            result = {"sync": {"status": "error"}, "conflicts": []}
        finally:
            sys.stdout = old
        return result

    def _print_sync_result(self, result: dict):
        """Print sync result summary."""
        if not result:
            print(f"\r{render.success('synced')}       ")
            return
        conflicts = result.get("conflicts", [])
        if conflicts:
            print(f"\r{render.warn(f'synced with {len(conflicts)} conflict(s)')}       ")
            for c in conflicts:
                print(f"  {render.warn(c)}")
        else:
            print(f"\r{render.success('synced')}       ")

    def _start_background_sync(self):
        """Start background sync checker if sync is enabled."""
        main_sync = MainSync(self.manager.home_dir, self.manager.config)
        if main_sync.is_sync_enabled():
            interval = self.manager.config.get("sync_interval", 60)
            self._bg_sync = BackgroundSync(main_sync, interval=interval)
            self._bg_sync.start()

    def _stop_background_sync(self):
        """Stop background sync checker."""
        if self._bg_sync:
            self._bg_sync.stop()
            self._bg_sync = None

    def _check_pending_sync(self):
        """Check if background sync detected remote changes and apply them."""
        if not self._bg_sync or not self._bg_sync.state.needs_apply:
            return
        # Apply: pull + reload
        sync_result = self._do_sync_quiet()
        self._bg_sync.state.mark_applied()
        self._refresh_tasks()
        conflicts = sync_result.get("conflicts", [])
        if conflicts:
            print(render.warn(f"↓ synced with {len(conflicts)} conflict(s)"))
            for c in conflicts:
                print(f"  {render.warn(c)}")
        else:
            print(render.info("↓ synced from remote"))
