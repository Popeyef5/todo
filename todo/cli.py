#!/usr/bin/env python3
"""
Todo CLI entry point
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
        'init', 'create', 'add', 'list', 'remove', 'config', 'nuke',
        'sync', 'share', '--help', '-h', '-i', '--interactive',
    }

    # Explicit interactive mode
    if sys.argv[1] in ('-i', '--interactive'):
        manager = TodoManager()
        target = sys.argv[2] if len(sys.argv) >= 3 else None
        _run_interactive(manager, initial_target=target)
        return

    # Unknown subcommand → interactive mode scoped to target
    if sys.argv[1] not in known_commands:
        target = sys.argv[1]
        manager = TodoManager()
        _run_interactive(manager, initial_target=target)
        return

    # Parse subcommands
    parser = argparse.ArgumentParser(description="Todo - Centralized TODO management")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # create
    create_parser = subparsers.add_parser('create', help='Create a new project')
    create_parser.add_argument('name', help='Project name')

    # init (alias for create)
    init_parser = subparsers.add_parser('init', help='Create a new project (alias for create)')
    init_parser.add_argument('name', help='Project name')

    # add
    add_parser = subparsers.add_parser('add', help='Add a task to a project')
    add_parser.add_argument('text', help='Task text')
    add_parser.add_argument('--project', '-p', help='Project name (required)')

    # list
    subparsers.add_parser('list', help='List all projects')

    # remove
    remove_parser = subparsers.add_parser('remove', help='Remove a project')
    remove_parser.add_argument('name', help='Project name')

    # config
    config_parser = subparsers.add_parser('config', help='View/set configuration')
    config_parser.add_argument('--editor', help='Set default editor')
    config_parser.add_argument('--auto-sync-on-edit', type=_str_to_bool, help='Auto-sync on edit')
    config_parser.add_argument('--github-token', help='GitHub API token')
    config_parser.add_argument('--gitlab-token', help='GitLab API token')
    config_parser.add_argument('--gitlab-host', help='GitLab host (for self-hosted)')
    config_parser.add_argument('--sync-interval', type=int, help='Background sync interval (seconds)')

    # nuke
    nuke_parser = subparsers.add_parser('nuke', help='Remove all todo data')
    nuke_parser.add_argument('--force', action='store_true', help='Skip confirmation')

    # sync
    sync_parser = subparsers.add_parser('sync', help='Sync operations')
    sync_subparsers = sync_parser.add_subparsers(dest='sync_action')
    sync_subparsers.add_parser('now', help='Sync now')
    sync_subparsers.add_parser('status', help='Show sync status')
    sync_setup = sync_subparsers.add_parser('setup', help='Setup git sync')
    sync_setup.add_argument('remote_url', help='Git remote URL')
    sync_clone = sync_subparsers.add_parser('clone', help='Clone from remote')
    sync_clone.add_argument('remote_url', help='Git remote URL')

    # share
    share_parser = subparsers.add_parser('share', help='Share a project via a group')
    share_subparsers = share_parser.add_subparsers(dest='share_action')
    share_add = share_subparsers.add_parser('add', help='Share a project with a group')
    share_add.add_argument('project', help='Project name')
    share_add.add_argument('group', help='Group name')
    share_add.add_argument('--remote', help='Git remote URL for the group')
    share_join = share_subparsers.add_parser('join', help='Join a shared group')
    share_join.add_argument('group', help='Group name')
    share_join.add_argument('remote_url', help='Git remote URL')

    args = parser.parse_args()
    manager = TodoManager()

    try:
        if args.command in ('create', 'init'):
            path = manager.create_project(args.name)
            print(f"Created project: {args.name} ({path})")

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

        elif args.command == 'list':
            projects = manager.list_projects()
            if not projects:
                print("No projects. Run 'todo create <name>' to create one.")
            else:
                for p in projects:
                    shared = f" (shared: {', '.join(p['shared_in'])})" if p['shared_in'] else ""
                    print(f"  {p['name']}: {p['todo_count']} pending{shared}")

        elif args.command == 'remove':
            if manager.remove_project(args.name):
                print(f"Removed: {args.name}")
            else:
                print(f"Not found: {args.name}")

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
            if not changed:
                print("Configuration:")
                for k, v in manager.config.config.items():
                    if k in ('github_token', 'gitlab_token') and v:
                        print(f"  {k}: ****")
                    else:
                        print(f"  {k}: {v}")

        elif args.command == 'nuke':
            if manager.nuke_all(force=args.force):
                print("All todo data removed. Run 'todo create <name>' to start fresh.")

        elif args.command == 'sync':
            if args.sync_action == 'setup':
                if manager.sync_setup(args.remote_url):
                    print(f"Git sync configured: {args.remote_url}")
                else:
                    print("Setup failed")
                    sys.exit(1)
            elif args.sync_action == 'clone':
                if manager.sync_clone(args.remote_url):
                    print("Cloned successfully")
                else:
                    print("Clone failed")
                    sys.exit(1)
            elif args.sync_action == 'status':
                from todo.sync.main_sync import MainSync
                from todo.sync.providers import detect_provider, parse_remote_url
                status = MainSync(manager.home_dir, manager.config).get_sync_status()
                print(f"  Enabled: {status['enabled']}")
                print(f"  Remote:  {status.get('remote_url', 'none')}")
                if status.get('remote_url'):
                    host, _, _ = parse_remote_url(status['remote_url'])
                    print(f"  Host:    {host or 'unknown'}")
            else:
                result = manager.sync()
                conflicts = result.get("conflicts", [])
                if conflicts:
                    print(f"Synced with {len(conflicts)} conflict(s):")
                    for c in conflicts:
                        print(f"  ⚠ {c}")
                else:
                    print("Synced")

        elif args.command == 'share':
            if args.share_action == 'add':
                manager.share_project(args.project, args.group, args.remote)
                print(f"Shared '{args.project}' via group '{args.group}'")
            elif args.share_action == 'join':
                if manager.share_join(args.group, args.remote_url):
                    print(f"Joined group '{args.group}'")
                else:
                    print("Join failed")
                    sys.exit(1)
            else:
                print("Use 'todo share --help'")

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
