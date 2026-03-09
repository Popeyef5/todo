#!/usr/bin/env python3
"""
Todo CLI entry point

Commands mirror the interactive REPL so that `todo <command> <args>`
behaves the same as `<command> <args>` inside the shell.
"""

import argparse
import sys

from todo.core.manager import TodoManager


def main():
    """Main CLI entry point"""
    # No arguments → interactive mode
    if len(sys.argv) == 1:
        manager = TodoManager()
        _run_interactive(manager)
        return

    known_commands = {
        'project', 'add', 'ls', 'show', 'toggle', 'check', 'uncheck',
        'edit', 'rm', 'addc', 'projects', 'status', 'setup',
        'push', 'pull', 'theme', 'group',
        'config', 'nuke', 'link', 'unlink', 'mcp',
        'sync', '--help', '-h',
    }

    # Unknown subcommand → interactive mode scoped to target
    if sys.argv[1] not in known_commands:
        target = sys.argv[1]
        manager = TodoManager()
        _run_interactive(manager, initial_target=target)
        return

    # Parse subcommands
    parser = argparse.ArgumentParser(description="Todo - Centralized TODO management")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # project
    project_parser = subparsers.add_parser('project', help='Project operations')
    project_subparsers = project_parser.add_subparsers(dest='project_action')
    project_new = project_subparsers.add_parser('new', help='Create a new project')
    project_new.add_argument('name', help='Project name')
    project_delete = project_subparsers.add_parser('delete', help='Delete a project')
    project_delete.add_argument('name', help='Project name')
    project_delete.add_argument('--force', action='store_true', help='Skip confirmation')

    # add
    add_parser = subparsers.add_parser('add', help='Add a task to a project')
    add_parser.add_argument('text', help='Task text')
    add_parser.add_argument('--project', '-p', help='Project name (required)')

    # ls
    ls_parser = subparsers.add_parser('ls', help='List tasks')
    ls_parser.add_argument('--project', '-p', help='Scope to a specific project')

    # show
    show_parser = subparsers.add_parser('show', help='Show task details')
    show_parser.add_argument('n', type=int, help='Task number (1-based)')
    show_parser.add_argument('--project', '-p', required=True, help='Project name')

    # toggle
    toggle_parser = subparsers.add_parser('toggle', help='Toggle task(s)')
    toggle_parser.add_argument('n', type=int, nargs='+', help='Task number(s) (1-based)')
    toggle_parser.add_argument('--project', '-p', required=True, help='Project name')

    # check
    check_parser = subparsers.add_parser('check', help='Mark task(s) done')
    check_parser.add_argument('n', type=int, nargs='+', help='Task number(s) (1-based)')
    check_parser.add_argument('--project', '-p', required=True, help='Project name')

    # uncheck
    uncheck_parser = subparsers.add_parser('uncheck', help='Mark task(s) pending')
    uncheck_parser.add_argument('n', type=int, nargs='+', help='Task number(s) (1-based)')
    uncheck_parser.add_argument('--project', '-p', required=True, help='Project name')

    # edit
    edit_parser = subparsers.add_parser('edit', help='Edit task text')
    edit_parser.add_argument('n', type=int, help='Task number (1-based)')
    edit_parser.add_argument('text', help='New task text')
    edit_parser.add_argument('--project', '-p', required=True, help='Project name')

    # rm
    rm_parser = subparsers.add_parser('rm', help='Remove a task')
    rm_parser.add_argument('n', type=int, help='Task number (1-based)')
    rm_parser.add_argument('--project', '-p', required=True, help='Project name')

    # addc
    addc_parser = subparsers.add_parser('addc', help='Add a child task under task #n')
    addc_parser.add_argument('n', type=int, help='Parent task number (1-based)')
    addc_parser.add_argument('text', help='Child task text')
    addc_parser.add_argument('--project', '-p', required=True, help='Project name')

    # projects
    subparsers.add_parser('projects', help='List projects')

    # status
    subparsers.add_parser('status', help='Show status')

    # setup
    subparsers.add_parser('setup', help='Interactive sync setup wizard')

    # push
    subparsers.add_parser('push', help='Push sync')

    # pull
    subparsers.add_parser('pull', help='Pull sync')

    # theme
    theme_parser = subparsers.add_parser('theme', help='View/set theme')
    theme_parser.add_argument('name', nargs='?', help='Theme name to set')

    # group
    group_parser = subparsers.add_parser('group', help='Group operations')
    group_subparsers = group_parser.add_subparsers(dest='group_action')
    group_new = group_subparsers.add_parser('new', help='Create a new group')
    group_new.add_argument('name', help='Group name')
    group_add = group_subparsers.add_parser('add', help='Add project to group')
    group_add.add_argument('project', help='Project name')
    group_add.add_argument('group_name', help='Group name')
    group_sync = group_subparsers.add_parser('sync', help='Sync a group')
    group_sync.add_argument('group_name', help='Group name')
    group_invite = group_subparsers.add_parser('invite', help='Invite collaborator')
    group_invite.add_argument('group_name', help='Group name')
    group_invite.add_argument('username', help='Username to invite')
    group_join = group_subparsers.add_parser('join', help='Join a shared group')
    group_join.add_argument('group_name', help='Group name')
    group_join.add_argument('url', help='Git remote URL')
    group_subparsers.add_parser('list', help='List groups')

    # config (CLI-only)
    config_parser = subparsers.add_parser('config', help='View/set configuration')
    config_parser.add_argument('--editor', help='Set default editor')
    config_parser.add_argument('--auto-sync-on-edit', type=_str_to_bool, help='Auto-sync on edit')
    config_parser.add_argument('--github-token', help='GitHub API token')
    config_parser.add_argument('--gitlab-token', help='GitLab API token')
    config_parser.add_argument('--gitlab-host', help='GitLab host (for self-hosted)')
    config_parser.add_argument('--sync-interval', type=int, help='Background sync interval (seconds)')
    config_parser.add_argument('--theme', help='UI theme (modern, cyber, minimal)')

    # nuke (CLI-only)
    nuke_parser = subparsers.add_parser('nuke', help='Remove all todo data')
    nuke_parser.add_argument('--force', action='store_true', help='Skip confirmation')

    # sync
    sync_parser = subparsers.add_parser('sync', help='Sync operations')
    sync_subparsers = sync_parser.add_subparsers(dest='sync_action')
    sync_subparsers.add_parser('now', help='Sync now')
    sync_clone = sync_subparsers.add_parser('clone', help='Clone from remote')
    sync_clone.add_argument('remote_url', help='Git remote URL')

    # link (CLI-only)
    link_parser = subparsers.add_parser('link', help='Create TODO.md symlink to a project')
    link_parser.add_argument('project', help='Project name')
    link_parser.add_argument('--path', help='Target directory (default: current dir)')

    # unlink (CLI-only)
    unlink_parser = subparsers.add_parser('unlink', help='Remove TODO.md symlink')
    unlink_parser.add_argument('project', help='Project name')
    unlink_parser.add_argument('--path', help='Target directory (default: current dir)')

    # mcp (CLI-only)
    subparsers.add_parser('mcp', help='Start MCP server (stdio transport)')

    args = parser.parse_args()
    manager = TodoManager()

    try:
        if args.command == 'project':
            if args.project_action == 'new':
                path = manager.create_project(args.name)
                print(f"Created project: {args.name} ({path})")
            elif args.project_action == 'delete':
                if not args.force:
                    confirm = input(f"Delete project '{args.name}' and all its tasks? [y/N]: ").strip().lower()
                    if confirm != 'y':
                        print("Cancelled")
                        return
                if manager.remove_project(args.name):
                    print(f"Deleted project: {args.name}")
                else:
                    print(f"Project '{args.name}' not found")
                    sys.exit(1)
            else:
                print("Usage: todo project {new|delete}")

        elif args.command == 'add':
            if not args.project:
                print("Error: --project is required")
                sys.exit(1)
            from todo.ui.tasks import add_task_to_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            add_task_to_file(path, args.text)
            print(f"Added to {args.project}: {args.text}")

        elif args.command == 'ls':
            from todo.ui.tasks import parse_tasks_from_file
            if args.project:
                path = manager.get_project_path(args.project)
                if not path.exists():
                    print(f"Project '{args.project}' not found")
                    sys.exit(1)
                tasks = parse_tasks_from_file(path, args.project)
            else:
                tasks = []
                project_paths = sorted(manager.get_all_project_paths(), key=lambda x: x[0])
                for name, path in project_paths:
                    tasks.extend(parse_tasks_from_file(path, name))
            if not tasks:
                print("No tasks found")
            else:
                current_project = None
                seen_projects = set()
                for i, task in enumerate(tasks, 1):
                    if task.project_name != current_project:
                        current_project = task.project_name
                        if current_project not in seen_projects:
                            seen_projects.add(current_project)
                            parts = current_project.split("/")
                            for j in range(1, len(parts)):
                                ancestor = "/".join(parts[:j])
                                if ancestor not in seen_projects:
                                    seen_projects.add(ancestor)
                                    depth = ancestor.count("/")
                                    display = ancestor.rsplit("/", 1)[-1] if "/" in ancestor else ancestor
                                    print(f"\n{'  ' * (depth + 1)}{display}")
                            depth = current_project.count("/")
                            display = current_project.rsplit("/", 1)[-1] if "/" in current_project else current_project
                            print(f"\n{'  ' * (depth + 1)}{display}")
                    status = "[x]" if task.checked else "[ ]"
                    indent = "  " * (current_project.count("/") + 1)
                    print(f"{indent}{i:3d}. {status} {task.text}")

        elif args.command == 'show':
            from todo.ui.tasks import parse_tasks_from_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            if args.n < 1 or args.n > len(tasks):
                print(f"Invalid task number: {args.n} (valid: 1-{len(tasks)})")
                sys.exit(1)
            task = tasks[args.n - 1]
            status = "[x]" if task.checked else "[ ]"
            print(f"  Task #{args.n}")
            print(f"  {status} {task.text}")
            print(f"  Project: {task.project_name}")
            print(f"  File:    {task.todo_path}")
            print(f"  Line:    {task.line_no + 1}")

        elif args.command == 'toggle':
            from todo.ui.tasks import parse_tasks_from_file, toggle_task_in_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            for n in args.n:
                if n < 1 or n > len(tasks):
                    print(f"Invalid task number: {n} (valid: 1-{len(tasks)})")
                    continue
                task = tasks[n - 1]
                new_state = toggle_task_in_file(task.todo_path, task.line_no)
                state_str = "done" if new_state else "pending"
                print(f"#{n} → {state_str}: {task.text}")

        elif args.command == 'check':
            from todo.ui.tasks import parse_tasks_from_file, toggle_task_in_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            for n in args.n:
                if n < 1 or n > len(tasks):
                    print(f"Invalid task number: {n} (valid: 1-{len(tasks)})")
                    continue
                task = tasks[n - 1]
                if not task.checked:
                    toggle_task_in_file(task.todo_path, task.line_no)
                    print(f"#{n} → done: {task.text}")
                else:
                    print(f"#{n} already done")

        elif args.command == 'uncheck':
            from todo.ui.tasks import parse_tasks_from_file, toggle_task_in_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            for n in args.n:
                if n < 1 or n > len(tasks):
                    print(f"Invalid task number: {n} (valid: 1-{len(tasks)})")
                    continue
                task = tasks[n - 1]
                if task.checked:
                    toggle_task_in_file(task.todo_path, task.line_no)
                    print(f"#{n} → pending: {task.text}")
                else:
                    print(f"#{n} already pending")

        elif args.command == 'edit':
            from todo.ui.tasks import parse_tasks_from_file, edit_task_in_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            if args.n < 1 or args.n > len(tasks):
                print(f"Invalid task number: {args.n} (valid: 1-{len(tasks)})")
                sys.exit(1)
            task = tasks[args.n - 1]
            if edit_task_in_file(task.todo_path, task.line_no, args.text):
                print(f"#{args.n} updated: {args.text}")
            else:
                print("Failed to edit task")
                sys.exit(1)

        elif args.command == 'rm':
            from todo.ui.tasks import parse_tasks_from_file, remove_task_from_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            if args.n < 1 or args.n > len(tasks):
                print(f"Invalid task number: {args.n} (valid: 1-{len(tasks)})")
                sys.exit(1)
            task = tasks[args.n - 1]
            if remove_task_from_file(task.todo_path, task.line_no):
                print(f"Removed: {task.text}")
            else:
                print("Failed to remove task")
                sys.exit(1)

        elif args.command == 'addc':
            from todo.ui.tasks import parse_tasks_from_file, add_task_to_file
            path = manager.get_project_path(args.project)
            if not path.exists():
                print(f"Project '{args.project}' not found")
                sys.exit(1)
            tasks = parse_tasks_from_file(path, args.project)
            if args.n < 1 or args.n > len(tasks):
                print(f"Invalid task number: {args.n} (valid: 1-{len(tasks)})")
                sys.exit(1)
            task = tasks[args.n - 1]
            child_indent = task.indent + "    "
            add_task_to_file(task.todo_path, args.text, indent=child_indent, after_line=task.line_no)
            print(f"Added child under #{args.n}: {args.text}")

        elif args.command == 'projects':
            from todo.ui.tasks import parse_tasks_from_file
            project_list = manager.list_projects()
            if not project_list:
                print("No projects found. Use 'todo project new <name>' to create one.")
            else:
                print("Projects:")
                sorted_projects = sorted(project_list, key=lambda p: p["name"])
                for p in sorted_projects:
                    try:
                        tasks = parse_tasks_from_file(p["path"], p["name"])
                        count = len(tasks)
                    except Exception:
                        count = 0
                    shared = p.get("shared_in", [])
                    ptype = f"shared: {', '.join(shared)}" if shared else "local"
                    depth = p["name"].count("/")
                    display_name = p["name"].rsplit("/", 1)[-1] if "/" in p["name"] else p["name"]
                    indent = "  " + "  " * depth
                    print(f"{indent}{display_name} ({count} tasks, {ptype})")

        elif args.command == 'status':
            from todo.ui.tasks import parse_tasks_from_file
            project_list = manager.list_projects()
            registry = manager.load_registry()
            groups = registry.get("groups", {})
            all_tasks = []
            for name, path in manager.get_all_project_paths():
                all_tasks.extend(parse_tasks_from_file(path, name))
            pending = sum(1 for t in all_tasks if not t.checked)
            git_dir = manager.home_dir / ".git"
            sync_status = "enabled" if git_dir.exists() else "disabled"
            print("Status:")
            print(f"  Projects:  {len(project_list)}")
            print(f"  Groups:    {len(groups)}")
            print(f"  Tasks:     {len(all_tasks)} ({pending} pending)")
            print(f"  Git sync:  {sync_status}")

        elif args.command == 'setup':
            from todo.ui.shell import TodoShell
            shell = TodoShell(manager)
            shell._cmd_setup([])

        elif args.command == 'push':
            print("Syncing...")
            result = manager.sync()
            print("Pushed")

        elif args.command == 'pull':
            print("Syncing...")
            result = manager.sync()
            conflicts = result.get("conflicts", [])
            if conflicts:
                print(f"Pulled with {len(conflicts)} conflict(s):")
                for c in conflicts:
                    print(f"  ⚠ {c}")
            else:
                print("Pulled")

        elif args.command == 'theme':
            from todo.ui.themes import set_theme, list_themes, load_custom_themes, get_theme
            load_custom_themes(manager.themes_dir)
            saved = manager.config.get("theme")
            if saved:
                set_theme(saved)
            if args.name:
                if set_theme(args.name):
                    manager.config.set("theme", args.name)
                    print(f"Theme set to '{args.name}'")
                else:
                    print(f"Unknown theme: {args.name} (available: {', '.join(list_themes())})")
            else:
                current = get_theme().name
                print(f"Current theme: {current}")
                print(f"Available: {', '.join(list_themes())}")

        elif args.command == 'group':
            if args.group_action == 'new':
                manager.create_group(args.name)
                print(f"Created group: {args.name}")
            elif args.group_action == 'add':
                manager.add_project_to_group(args.project, args.group_name)
                print(f"Added '{args.project}' to group '{args.group_name}'")
            elif args.group_action == 'sync':
                print(f"Use interactive mode for the group sync wizard: run 'todo' then 'setup'")
            elif args.group_action == 'invite':
                if manager.invite_to_group(args.group_name, args.username):
                    print(f"Invited '{args.username}' to group '{args.group_name}'")
                else:
                    print("Invite failed")
                    sys.exit(1)
            elif args.group_action == 'join':
                if manager.share_join(args.group_name, args.url):
                    print(f"Joined group '{args.group_name}'")
                else:
                    print("Join failed")
                    sys.exit(1)
            elif args.group_action == 'list':
                registry = manager.load_registry()
                groups = registry.get("groups", {})
                if not groups:
                    print("No groups found")
                else:
                    print("Groups:")
                    for name, info in groups.items():
                        projects = info.get("projects", [])
                        has_remote = bool(info.get("remote"))
                        sync_icon = "🔗" if has_remote else "📝"
                        print(f"  {sync_icon} {name} ({len(projects)} projects)")
            else:
                print("Usage: todo group {new|add|sync|invite|join|list}")

        elif args.command == 'config':
            changed = False
            if args.editor:
                manager.config.set('editor', args.editor)
                print(f"Set editor: {args.editor}")
                changed = True
            if args.auto_sync_on_edit is not None:
                manager.config.set('auto_sync_on_edit', args.auto_sync_on_edit)
                print(f"Auto-sync on edit: {args.auto_sync_on_edit}")
                changed = True
            if args.github_token:
                manager.config.set('github_token', args.github_token)
                print("GitHub token configured")
                changed = True
            if args.gitlab_token:
                manager.config.set('gitlab_token', args.gitlab_token)
                print("GitLab token configured")
                changed = True
            if args.gitlab_host:
                manager.config.set('gitlab_host', args.gitlab_host)
                print(f"GitLab host: {args.gitlab_host}")
                changed = True
            if args.sync_interval is not None:
                manager.config.set('sync_interval', args.sync_interval)
                print(f"Sync interval: {args.sync_interval}s")
                changed = True
            if args.theme:
                from todo.ui.themes import set_theme, list_themes, load_custom_themes
                load_custom_themes(manager.themes_dir)
                if set_theme(args.theme):
                    manager.config.set('theme', args.theme)
                    print(f"Theme: {args.theme}")
                    changed = True
                else:
                    print(f"Unknown theme: {args.theme} (available: {', '.join(list_themes())})")
            if not changed:
                print("Configuration:")
                for k, v in manager.config.config.items():
                    if k in ('github_token', 'gitlab_token') and v:
                        print(f"  {k}: ****")
                    else:
                        print(f"  {k}: {v}")

        elif args.command == 'nuke':
            if manager.nuke_all(force=args.force):
                print("All todo data removed. Run 'todo project new <name>' to start fresh.")

        elif args.command == 'sync':
            if args.sync_action == 'clone':
                if manager.sync_clone(args.remote_url):
                    print("Cloned successfully")
                else:
                    print("Clone failed")
                    sys.exit(1)
            else:
                # 'now' or no subcommand — just sync
                result = manager.sync()
                conflicts = result.get("conflicts", [])
                if conflicts:
                    print(f"Synced with {len(conflicts)} conflict(s):")
                    for c in conflicts:
                        print(f"  ⚠ {c}")
                else:
                    print("Synced")

        elif args.command == 'link':
            from pathlib import Path
            target_dir = Path(args.path) if args.path else None
            symlink = manager.link_project(args.project, target_dir)
            print(f"Linked {args.project} → {symlink}")

        elif args.command == 'unlink':
            from pathlib import Path
            target_dir = Path(args.path) if args.path else None
            if manager.unlink_project(args.project, target_dir):
                print(f"Unlinked {args.project}")
            else:
                print("No TODO.md symlink found")

        elif args.command == 'mcp':
            from todo.mcp.server import run_server
            run_server()

        else:
            parser.print_help()

    except KeyboardInterrupt:
        print("\nAborted")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _run_interactive(manager, initial_target=None):
    """Launch the TUI, falling back to the basic shell if curses is unavailable."""
    try:
        from todo.ui.tui import TodoTUI
        tui = TodoTUI(manager, initial_target=initial_target)
        tui.run()
    except ImportError:
        from todo.ui.shell import TodoShell
        shell = TodoShell(manager, initial_target=initial_target)
        shell.run()


def _str_to_bool(v):
    if v.lower() in ('true', '1', 'yes'):
        return True
    elif v.lower() in ('false', '0', 'no'):
        return False
    raise argparse.ArgumentTypeError(f"Expected true/false, got: {v}")


if __name__ == "__main__":
    main()
