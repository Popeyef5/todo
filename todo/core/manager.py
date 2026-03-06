import subprocess
import shutil
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .config import TodoConfig
from .conflict import ConflictManager
from ..sync.main_sync import MainSync
from ..sync.shared_sync import SharedSync
from ..sync.providers import parse_remote_url, detect_provider
from ..ui.tasks import ensure_task_ids


class TodoManager:
    """Main Todo manager — centralized ~/.todo/ directory"""

    def __init__(self):
        self.home_dir = Path.home() / ".todo"
        self.config_file = self.home_dir / "config.json"
        self.registry_file = self.home_dir / "registry.json"
        self.data_dir = self.home_dir / "data"
        self.shared_dir = self.home_dir / "shared"
        self.cache_dir = self.home_dir / "cache"
        self.config = TodoConfig(self.config_file)
        self.conflict_manager = ConflictManager(self.cache_dir)
        self.ensure_structure()

    def ensure_structure(self):
        """Create ~/.todo/ directory structure if needed"""
        self.home_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)
        self.shared_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)

        if not self.registry_file.exists():
            self.save_registry({"projects": {}, "groups": {}})

    # ── Registry ──────────────────────────────────────────────

    def load_registry(self) -> Dict:
        """Load registry.json"""
        default = {"projects": {}, "groups": {}}
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r") as f:
                    data = json.load(f)
                return {**default, **data}
            except (json.JSONDecodeError, IOError):
                pass
        return default

    def save_registry(self, registry: Dict):
        """Save registry.json"""
        with open(self.registry_file, "w") as f:
            json.dump(registry, f, indent=2)

    # ── Project CRUD ──────────────────────────────────────────

    def create_project(self, name: str) -> Path:
        """Create a new project: data/<name>.todo and register it"""
        registry = self.load_registry()
        if name in registry["projects"]:
            raise ValueError(f"Project '{name}' already exists")

        todo_path = self.data_dir / f"{name}.todo"
        if not todo_path.exists():
            todo_path.write_text("")
        ensure_task_ids(todo_path)

        registry["projects"][name] = {
            "created": datetime.now().isoformat(),
            "shared_in": [],
        }
        self.save_registry(registry)
        return todo_path

    def list_projects(self) -> List[Dict]:
        """Return list of project info dicts"""
        registry = self.load_registry()
        projects = []
        for name, info in registry["projects"].items():
            todo_path = self.data_dir / f"{name}.todo"
            todo_count = 0
            if todo_path.exists():
                for line in todo_path.read_text().splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- [ ]"):
                        todo_count += 1
            projects.append({
                "name": name,
                "path": str(todo_path),
                "created": info.get("created", ""),
                "shared_in": info.get("shared_in", []),
                "todo_count": todo_count,
            })
        return projects

    def remove_project(self, name: str) -> bool:
        """Remove a project file and its registry entry"""
        registry = self.load_registry()
        if name not in registry["projects"]:
            return False

        todo_path = self.data_dir / f"{name}.todo"
        if todo_path.exists():
            todo_path.unlink()

        # Remove from any shared groups
        for group_name in list(registry["projects"][name].get("shared_in", [])):
            group_info = registry["groups"].get(group_name)
            if group_info and name in group_info["projects"]:
                group_info["projects"].remove(name)
                shared_file = self.shared_dir / group_name / f"{name}.todo"
                if shared_file.exists():
                    shared_file.unlink()

        del registry["projects"][name]
        self.save_registry(registry)
        return True

    def get_project_path(self, name: str) -> Path:
        """Return Path to the .todo file in data/"""
        return self.data_dir / f"{name}.todo"

    def get_all_project_paths(self) -> List[tuple]:
        """Return list of (name, Path) for all projects (data/ and shared/)"""
        paths = []
        registry = self.load_registry()

        for name in registry["projects"]:
            paths.append((name, self.data_dir / f"{name}.todo"))

        # Also include any files in shared/ that aren't already in data/
        if self.shared_dir.exists():
            known_names = set(registry["projects"].keys())
            for group_dir in self.shared_dir.iterdir():
                if group_dir.is_dir() and not group_dir.name.startswith("."):
                    for todo_file in group_dir.glob("*.todo"):
                        stem = todo_file.stem
                        if stem not in known_names:
                            paths.append((stem, todo_file))
                            known_names.add(stem)

        return paths

    # ── Groups ──────────────────────────────────────────────

    def create_group(self, name: str):
        """Creates a group entry in the registry and shared/<name>/ directory"""
        registry = self.load_registry()
        if name in registry["groups"]:
            raise ValueError(f"Group '{name}' already exists")

        group_dir = self.shared_dir / name
        group_dir.mkdir(parents=True, exist_ok=True)

        registry["groups"][name] = {
            "remote": None,
            "projects": [],
            "created": datetime.now().isoformat(),
        }
        self.save_registry(registry)

    def add_project_to_group(self, project_name: str, group_name: str):
        """Adds an existing project to an existing group"""
        registry = self.load_registry()

        if project_name not in registry["projects"]:
            raise ValueError(f"Project '{project_name}' not found")
        if group_name not in registry["groups"]:
            raise ValueError(f"Group '{group_name}' not found")
        if project_name in registry["groups"][group_name]["projects"]:
            raise ValueError(f"Project '{project_name}' is already in group '{group_name}'")

        src = self.data_dir / f"{project_name}.todo"
        dst = self.shared_dir / group_name / f"{project_name}.todo"
        if src.exists():
            shutil.copy2(src, dst)

        registry["groups"][group_name]["projects"].append(project_name)
        if group_name not in registry["projects"][project_name].get("shared_in", []):
            registry["projects"][project_name].setdefault("shared_in", []).append(group_name)

        self.save_registry(registry)

    def setup_group_sync(self, group_name: str, remote_url: str) -> bool:
        """Sets up git remote for an existing group"""
        registry = self.load_registry()
        if group_name not in registry["groups"]:
            raise ValueError(f"Group '{group_name}' not found")

        group_dir = self.shared_dir / group_name
        sync = SharedSync(group_dir, self.config)
        if not sync.setup(remote_url):
            return False

        registry["groups"][group_name]["remote"] = remote_url
        self.save_registry(registry)
        return True

    def reconstitute_groups(self) -> list:
        """After a fresh clone, reconstitute groups with remotes but no local directory"""
        registry = self.load_registry()
        reconstituted = []

        for group_name, group_info in registry["groups"].items():
            remote = group_info.get("remote")
            group_dir = self.shared_dir / group_name
            if remote and not group_dir.exists():
                sync = SharedSync(group_dir, self.config)
                if sync.clone(remote):
                    for todo_file in group_dir.glob("*.todo"):
                        dst = self.data_dir / todo_file.name
                        shutil.copy2(todo_file, dst)
                    reconstituted.append(group_name)

        return reconstituted

    def invite_to_group(self, group_name: str, username: str) -> bool:
        """Invite a user as collaborator on a group's remote repo.

        Uses the stored remote URL to detect provider (GitHub/GitLab)
        and calls the provider API to add the collaborator.
        """
        registry = self.load_registry()
        if group_name not in registry["groups"]:
            raise ValueError(f"Group '{group_name}' not found")

        remote = registry["groups"][group_name].get("remote")
        if not remote:
            raise ValueError(f"Group '{group_name}' has no remote configured")

        host, owner, repo = parse_remote_url(remote)
        if not owner or not repo:
            raise ValueError(f"Cannot parse remote URL: {remote}")

        provider = detect_provider(remote, self.config)
        return provider.add_collaborator(owner, repo, username)

    def join_group(self, group_name: str, remote_url: str) -> bool:
        """Join an existing shared group by cloning its remote repo."""
        group_dir = self.shared_dir / group_name
        if group_dir.exists():
            raise ValueError(f"Group '{group_name}' already exists locally")

        sync = SharedSync(group_dir, self.config)
        if not sync.clone(remote_url):
            return False

        registry = self.load_registry()

        registry["groups"][group_name] = {
            "remote": remote_url,
            "projects": [],
            "created": datetime.now().isoformat(),
        }

        for todo_file in group_dir.glob("*.todo"):
            name = todo_file.stem
            dst = self.data_dir / f"{name}.todo"
            shutil.copy2(todo_file, dst)
            ensure_task_ids(dst)

            registry["groups"][group_name]["projects"].append(name)

            if name not in registry["projects"]:
                registry["projects"][name] = {
                    "created": datetime.now().isoformat(),
                    "shared_in": [group_name],
                }
            elif group_name not in registry["projects"][name].get("shared_in", []):
                registry["projects"][name].setdefault("shared_in", []).append(group_name)

        self.save_registry(registry)
        return True

    # ── Sharing ───────────────────────────────────────────────

    def share_project(self, project_name: str, group_name: str, remote_url: str = None) -> bool:
        """Share a project via a group"""
        registry = self.load_registry()

        if project_name not in registry["projects"]:
            raise ValueError(f"Project '{project_name}' not found")

        # Create group dir
        group_dir = self.shared_dir / group_name
        group_dir.mkdir(parents=True, exist_ok=True)

        # Copy file to shared/
        src = self.data_dir / f"{project_name}.todo"
        dst = group_dir / f"{project_name}.todo"
        if src.exists():
            shutil.copy2(src, dst)

        # Init git in shared group if needed
        if not (group_dir / ".git").exists():
            sync = SharedSync(group_dir, self.config)
            if remote_url:
                sync.setup(remote_url)
            else:
                subprocess.run(["git", "init"], cwd=group_dir, capture_output=True)

        # Update registry
        if group_name not in registry["groups"]:
            registry["groups"][group_name] = {
                "remote": remote_url,
                "projects": [],
                "created": datetime.now().isoformat(),
            }

        if project_name not in registry["groups"][group_name]["projects"]:
            registry["groups"][group_name]["projects"].append(project_name)

        if group_name not in registry["projects"][project_name]["shared_in"]:
            registry["projects"][project_name]["shared_in"].append(group_name)

        if remote_url and not registry["groups"][group_name].get("remote"):
            registry["groups"][group_name]["remote"] = remote_url

        self.save_registry(registry)
        return True

    def share_join(self, group_name: str, remote_url: str) -> bool:
        """Clone a shared group repo and copy files to data/"""
        group_dir = self.shared_dir / group_name
        if group_dir.exists():
            raise ValueError(f"Group '{group_name}' already exists locally")

        sync = SharedSync(group_dir, self.config)
        if not sync.clone(remote_url):
            return False

        registry = self.load_registry()

        # Register group
        registry["groups"][group_name] = {
            "remote": remote_url,
            "projects": [],
            "created": datetime.now().isoformat(),
        }

        # Copy .todo files from cloned group into data/
        for todo_file in group_dir.glob("*.todo"):
            name = todo_file.stem
            dst = self.data_dir / f"{name}.todo"
            shutil.copy2(todo_file, dst)

            registry["groups"][group_name]["projects"].append(name)

            if name not in registry["projects"]:
                registry["projects"][name] = {
                    "created": datetime.now().isoformat(),
                    "shared_in": [group_name],
                }
            elif group_name not in registry["projects"][name]["shared_in"]:
                registry["projects"][name]["shared_in"].append(group_name)

        self.save_registry(registry)
        return True

    # ── Sync ──────────────────────────────────────────────────

    def sync(self) -> dict:
        """Full sync: pull shared → commit main → push main → copy to shared → push shared.
        
        Returns dict with sync results including any conflicts detected.
        """
        registry = self.load_registry()
        main_sync = MainSync(self.home_dir, self.config)
        conflicts = []

        # 1. Pull shared repos → copy changed files to data/ (with conflict check)
        for group_name, group_info in registry["groups"].items():
            group_dir = self.shared_dir / group_name
            if not group_dir.exists() or not (group_dir / ".git").exists():
                continue
            shared = SharedSync(group_dir, self.config)
            shared.pull()
            for todo_file in group_dir.glob("*.todo"):
                dst = self.data_dir / todo_file.name
                if dst.exists():
                    remote_content = todo_file.read_text()
                    conflict = self.conflict_manager.check_conflicts(dst, remote_content)
                    if conflict:
                        # Both sides changed — do task-level merge
                        result = self.conflict_manager.merge_files(dst, remote_content)
                        dst.write_text(result["merged_content"])
                        if result["conflicts"]:
                            conflicts.extend(result["conflicts"])
                        self.conflict_manager.update_checksum(dst)
                    else:
                        shutil.copy2(todo_file, dst)
                        self.conflict_manager.update_checksum(dst)
                else:
                    shutil.copy2(todo_file, dst)
                    self.conflict_manager.update_checksum(dst)
                ensure_task_ids(dst)

        # 2. Ensure task IDs on all project files
        for name, path in self.get_all_project_paths():
            ensure_task_ids(path)

        # 3. Commit + smart sync main repo
        if (self.home_dir / ".git").exists():
            sync_result = main_sync.full_sync()
        else:
            sync_result = {"status": "no_git", "pulled": False, "pushed": False}

        # 4. Copy shared project files from data/ → shared/<group>/ (with conflict check)
        for group_name, group_info in registry["groups"].items():
            group_dir = self.shared_dir / group_name
            if not group_dir.exists():
                continue
            for project_name in group_info.get("projects", []):
                src = self.data_dir / f"{project_name}.todo"
                if src.exists():
                    dst = group_dir / f"{project_name}.todo"
                    if dst.exists():
                        local_content = src.read_text()
                        conflict = self.conflict_manager.check_conflicts(dst, local_content)
                        if conflict:
                            result = self.conflict_manager.merge_files(dst, local_content)
                            dst.write_text(result["merged_content"])
                            if result["conflicts"]:
                                conflicts.extend(result["conflicts"])
                        else:
                            shutil.copy2(src, dst)
                    else:
                        shutil.copy2(src, dst)

        # 5. Commit+push each shared repo
        for group_name in registry["groups"]:
            group_dir = self.shared_dir / group_name
            if not group_dir.exists() or not (group_dir / ".git").exists():
                continue
            shared = SharedSync(group_dir, self.config)
            shared.full_sync()

        return {"sync": sync_result, "conflicts": conflicts}

    def sync_setup(self, remote_url: str) -> bool:
        """Setup git in ~/.todo/ with remote"""
        main_sync = MainSync(self.home_dir, self.config)
        return main_sync.setup(remote_url)

    def sync_clone(self, remote_url: str) -> bool:
        """Clone existing ~/.todo/ from remote"""
        main_sync = MainSync(self.home_dir, self.config)
        result = main_sync.setup(remote_url, clone=True)
        if result:
            self.reconstitute_groups()
        return result

    # ── Nuke ──────────────────────────────────────────────────

    def nuke_all(self, force: bool = False) -> bool:
        """Remove everything in ~/.todo/"""
        if not force:
            response = input("This will DELETE all todo data in ~/.todo/. Are you sure? [y/N]: ").strip().lower()
            if response != "y":
                return False

        if self.home_dir.exists():
            shutil.rmtree(self.home_dir)
        return True
