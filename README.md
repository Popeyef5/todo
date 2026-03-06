# Todo

A git-like TODO management system with an interactive CLI and multi-device synchronization.

## Features

🚀 **Interactive CLI** - Manage todos directly from a terminal prompt  
📱 **Multi-device sync** - Keep todos in sync across all your devices  
🔄 **Conflict detection** - Smart merging with hash-based conflict detection  
🔗 **Symlink management** - Central view of all todos across projects  
⚡ **Auto-sync** - Changes sync automatically on enter/exit  

## Quick Start

```bash
# Install
pip install todo

# Initialize a project
cd ~/my-project
todo init

# Launch interactive mode
todo

# Or scope to a specific project
todo my-project
```

## Interactive Mode

Running `todo` with no arguments enters an interactive session:

```
  todo  interactive mode
  Type help for commands, q to quit

╭ my-project — 3 pending, 1 done ──────────────────────╮
│  my-project › backend.todo                            │
│    1 [ ] implement auth                               │
│    2 [x] add tests                                    │
│    3 [ ] deploy                                       │
╰───────────────────────────────────────────────────────╯
todo (my-project)> toggle 1
✓ #1 → done: implement auth

todo (my-project)> add "write docs"
✓ Added: write docs

todo (my-project)> q
  bye 👋
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `projects` | List all projects |
| `use <project>` | Switch to a project scope |
| `use` | Switch to global scope (all projects) |
| `ls` | List tasks |
| `show <n>` | Show task details |
| `add <text>` | Add a new task |
| `toggle <n>` / `t <n>` / `<n>` | Toggle a task checkbox |
| `check <n>` | Mark task as done |
| `uncheck <n>` | Mark task as not done |
| `edit <n> <text>` | Edit task text |
| `rm <n>` | Remove a task |
| `new <name>` | Create a new .todo file |
| `sync` | Sync all files |
| `push` | Push to global |
| `pull` | Pull from projects |
| `status` | Show status |
| `groups` | List groups |
| `q` / `quit` | Exit |

## CLI Commands (non-interactive)

### Project Management
- `todo init` - Initialize project in current directory
- `todo init --name "project-name" --virtual` - Create virtual project
- `todo create "project-name" [--description "desc"]` - Create virtual project
- `todo add "name.of.todo"` - Add new todo file to current project
- `todo add "name.of.todo" --project "project-name"` - Add todo to specific project
- `todo scan [--depth N]` - Scan for existing .todo files
- `todo list` - List tracked projects

### Synchronization  
- `todo pull` - Pull all projects to central global
- `todo push` - Push central global to all projects
- `todo view --project X` - Filtered view by project
- `todo view --grep "term"` - Filtered view by search

### Multi-Device Sync
- `todo sync setup <url>` - Setup git sync
- `todo sync clone <url>` - Clone existing todos
- `todo sync status` - Show sync status
- `todo sync now` - Force sync

### Configuration
- `todo config --editor vim` - Set editor
- `todo config --auto-sync-on-edit false` - Disable auto-sync
- `todo config --toc-mode simple` - Set TOC style

## Directory Structure

```
~/.todo/
├── .global.todo             # Central view of all todos
├── links/                   # Symlinks to all tracked todos
│   └── project-name/
│       └── feature.todo -> /path/to/project/feature.todo
├── projects/                # Virtual projects
│   └── project-name/
├── groups/                  # Project groups
├── cache/                   # Conflict detection cache
├── config.json              # Configuration
├── .todo.json              # Project registry
└── .git/                    # Git repo for sync (optional)
```

## License

MIT License - see LICENSE file for details.
