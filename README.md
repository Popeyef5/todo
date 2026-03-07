# Todo

A terminal-based TODO manager with a split-pane TUI, project groups, and multi-device sync via git.

## Features

🖥️ **Split-pane TUI** — Persistent task panel + CLI in one screen, with modal and REPL modes  
📁 **Projects & groups** — Organize todos into projects, share them via groups  
📱 **Multi-device sync** — Git-backed sync across devices with background polling  
🔄 **Smart merge** — Task-level conflict detection using stable IDs and checksums  
⚡ **Auto-sync** — Changes propagate automatically on enter/exit  

## Quick Start

```bash
# Install
pip install -e .

# Launch interactive TUI
todo

# Scope to a specific project
todo my-project

# Create a project from the CLI
todo create my-project
```

## Interactive TUI

Running `todo` launches a curses-based split-pane interface. The upper half shows tasks, the lower half is a CLI output area with an input prompt.

### Two modes

- **REPL mode** (default) — Type commands in the input prompt
- **Modal mode** (`Ctrl+T`) — Navigate tasks with `j`/`k`, act with single keys
- **Fullscreen** (`Ctrl+F`) — Expand the task panel to fill the screen (modal only, exits on `Ctrl+T`)

### REPL Commands

| Command | Description |
|---------|-------------|
| `projects` | List all projects |
| `use <project>` | Switch to a project scope |
| `use` | Switch to global scope (all projects) |
| `ls` | List tasks |
| `show <n>` | Show task details |
| `add <text>` | Add a new task |
| `toggle <n>` / `t <n>` / `<n>` | Toggle a task |
| `check <n>` | Mark task as done |
| `uncheck <n>` | Mark task as not done |
| `edit <n> <text>` / `e <n> <text>` | Edit task text |
| `rm <n>` | Remove a task (and children) |
| `new <name>` | Create a new project |
| `share` | Share a project via a group |
| `setup` | Configure sync (guided wizard) |
| `sync` | Sync all files |
| `push` | Push changes |
| `pull` | Pull changes |
| `groups` | List groups |
| `status` | Show status |
| `clear` | Clear output |
| `q` / `quit` | Exit |

### Modal Keys

| Key | Action |
|-----|--------|
| `j` / `k` / `↑` / `↓` | Navigate tasks |
| `t` | Toggle task |
| `a` | Add task |
| `A` | Add child task |
| `e` | Edit task |
| `d` | Delete task |
| `u` | Switch project (use) |
| `c` | Collapse/expand project |
| `q` | Quit |

## CLI Commands

For scripting and bootstrapping — most day-to-day work is done in the TUI.

```bash
# Project management
todo create <name>                  # Create a new project
todo add <text> -p <project>        # Add a task

# Sync
todo sync                           # Sync now
todo sync clone <url>               # Clone todos from a remote (new device setup)
todo share join <group> <url>       # Join a shared group

# Configuration
todo config                         # View config
todo config --editor vim            # Set editor
todo config --github-token <token>  # Set GitHub token
todo config --auto-sync-on-edit false

# Maintenance
todo nuke [--force]                 # Delete all todo data
```

## Directory Structure

```
~/.todo/
├── data/                   # Project .todo files (one per project)
│   ├── my-project.todo
│   └── work.todo
├── shared/                 # Shared group directories (each is a git repo)
│   └── team/
│       ├── work.todo
│       └── .git/
├── cache/                  # Checksums for conflict detection
│   └── checksums.json
├── config.json             # Configuration (editor, tokens, sync settings)
├── registry.json           # Project and group registry
└── .git/                   # Main git repo for multi-device sync (optional)
```

## Sync Architecture

Each device has a main `~/.todo/` git repo for syncing private data across devices. Shared groups live in `shared/<group>/`, each with its own git repo that collaborators can push/pull to.

On sync:
1. Commit local changes in main repo
2. Fetch + pull main (if behind) — gets own changes from other devices
3. Fetch + pull each shared group (if behind) — gets collaborator changes
4. Merge group files into `data/` with task-level conflict resolution
5. Copy `data/` back to shared groups
6. Commit + push main and each group

Conflicts are detected via stored checksums (3-way: local, remote, last-known). When both sides diverge, tasks are merged by stable ID — local wins on text conflicts.

## License

MIT
