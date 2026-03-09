import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch

from todo.core.manager import TodoManager


class TestManagerInit:

    def test_creates_directory_structure(self, manager):
        assert manager.home_dir.exists()
        assert manager.data_dir.exists()
        assert manager.shared_dir.exists()
        assert manager.cache_dir.exists()
        assert manager.registry_file.exists()

    def test_default_registry(self, manager):
        reg = manager.load_registry()
        assert reg["projects"] == {}
        assert reg["groups"] == {}


class TestProjectCRUD:

    def test_create_project(self, manager):
        path = manager.create_project("myproject")
        assert path.exists()
        assert path.name == "myproject.todo"
        reg = manager.load_registry()
        assert "myproject" in reg["projects"]

    def test_create_duplicate_raises(self, manager):
        manager.create_project("dup")
        with pytest.raises(ValueError, match="already exists"):
            manager.create_project("dup")

    def test_list_projects(self, manager):
        manager.create_project("alpha")
        manager.create_project("beta")
        projects = manager.list_projects()
        names = [p["name"] for p in projects]
        assert "alpha" in names
        assert "beta" in names

    def test_list_projects_counts_todos(self, manager):
        manager.create_project("counted")
        path = manager.get_project_path("counted")
        path.write_text("- [ ] one\n- [ ] two\n- [x] done\n")
        projects = manager.list_projects()
        proj = [p for p in projects if p["name"] == "counted"][0]
        assert proj["todo_count"] == 2  # only unchecked

    def test_remove_project(self, manager):
        manager.create_project("removeme")
        assert manager.remove_project("removeme") is True
        assert not manager.get_project_path("removeme").exists()
        reg = manager.load_registry()
        assert "removeme" not in reg["projects"]

    def test_remove_nonexistent_returns_false(self, manager):
        assert manager.remove_project("ghost") is False

    def test_remove_project_cleans_up_groups(self, manager):
        manager.create_project("shared_proj")
        manager.create_group("team")
        manager.add_project_to_group("shared_proj", "team")
        manager.remove_project("shared_proj")
        reg = manager.load_registry()
        assert "shared_proj" not in reg["groups"]["team"]["projects"]

    def test_get_project_path(self, manager):
        path = manager.get_project_path("test")
        assert str(path).endswith("data/test.todo")

    def test_get_all_project_paths(self, manager):
        manager.create_project("p1")
        manager.create_project("p2")
        paths = manager.get_all_project_paths()
        names = [name for name, _ in paths]
        assert "p1" in names
        assert "p2" in names


class TestGroups:

    def test_create_group(self, manager):
        manager.create_group("team")
        reg = manager.load_registry()
        assert "team" in reg["groups"]
        assert (manager.shared_dir / "team").is_dir()

    def test_create_duplicate_group_raises(self, manager):
        manager.create_group("team")
        with pytest.raises(ValueError, match="already exists"):
            manager.create_group("team")

    def test_add_project_to_group(self, manager):
        manager.create_project("proj")
        manager.create_group("team")
        # Write some content so copy works
        manager.get_project_path("proj").write_text("- [ ] task\n")
        manager.add_project_to_group("proj", "team")

        reg = manager.load_registry()
        assert "proj" in reg["groups"]["team"]["projects"]
        assert "team" in reg["projects"]["proj"]["shared_in"]
        # File should be copied to shared/
        shared_file = manager.shared_dir / "team" / "proj.todo"
        assert shared_file.exists()

    def test_add_project_to_nonexistent_group_raises(self, manager):
        manager.create_project("proj")
        with pytest.raises(ValueError, match="not found"):
            manager.add_project_to_group("proj", "ghost")

    def test_add_nonexistent_project_to_group_raises(self, manager):
        manager.create_group("team")
        with pytest.raises(ValueError, match="not found"):
            manager.add_project_to_group("ghost", "team")

    def test_add_duplicate_project_to_group_raises(self, manager):
        manager.create_project("proj")
        manager.create_group("team")
        manager.add_project_to_group("proj", "team")
        with pytest.raises(ValueError, match="already in group"):
            manager.add_project_to_group("proj", "team")


class TestShareProject:

    def test_share_creates_group_if_needed(self, manager):
        manager.create_project("proj")
        manager.get_project_path("proj").write_text("- [ ] task\n")
        manager.share_project("proj", "newgroup")
        reg = manager.load_registry()
        assert "newgroup" in reg["groups"]
        assert "proj" in reg["groups"]["newgroup"]["projects"]

    def test_share_copies_file_to_shared(self, manager):
        manager.create_project("proj")
        content = "- [ ] original\n"
        manager.get_project_path("proj").write_text(content)
        manager.share_project("proj", "team")
        shared = manager.shared_dir / "team" / "proj.todo"
        assert shared.exists()
        assert shared.read_text() == content

    def test_share_nonexistent_project_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            manager.share_project("ghost", "team")


class TestSyncDataToShared:
    """Test that local data/ edits propagate to shared/ during sync (no git)."""

    def test_data_changes_copied_to_shared(self, manager):
        """When data/ file is edited and no git is set up, sync should copy to shared/"""
        manager.create_project("proj")
        manager.create_group("team")
        manager.add_project_to_group("proj", "team")

        # Simulate local edit
        manager.get_project_path("proj").write_text("- [ ] updated task\n")

        result = manager.sync()
        shared_file = manager.shared_dir / "team" / "proj.todo"
        assert "updated task" in shared_file.read_text()

    def test_sync_returns_no_git_status_without_repo(self, manager):
        result = manager.sync()
        assert result["sync"]["status"] == "no_git"
        assert result["conflicts"] == []
        assert result["group_errors"] == {}


class TestSyncSharedToData:
    """Test that remote changes in shared/ propagate to data/ during sync."""

    def _setup_group_with_git(self, manager, project_name="proj", group_name="team"):
        """Create a project+group with a fake git repo in shared/."""
        manager.create_project(project_name)
        manager.create_group(group_name)
        manager.get_project_path(project_name).write_text("- [ ] original\n")
        manager.add_project_to_group(project_name, group_name)
        # Init a bare git dir so sync doesn't skip the group
        group_dir = manager.shared_dir / group_name
        (group_dir / ".git").mkdir(exist_ok=True)
        return group_dir

    def test_remote_changes_merged_to_data(self, manager):
        """When shared/ file has new content from a pull, it merges into data/."""
        group_dir = self._setup_group_with_git(manager)

        # Simulate a remote change arriving in shared/ after pull
        shared_file = group_dir / "proj.todo"
        shared_file.write_text("- [ ] original\n- [ ] from remote\n")

        with patch("todo.sync.shared_sync.SharedSync.smart_fetch",
                    return_value={"status": "behind", "local_sha": "a", "remote_sha": "b"}), \
             patch("todo.sync.shared_sync.SharedSync.pull", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync.push", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync._commit_all_changes", return_value=True):
            result = manager.sync()

        data_content = manager.get_project_path("proj").read_text()
        assert "from remote" in data_content
        assert result["group_errors"] == {}

    def test_remote_changes_merged_to_directory_project(self, manager):
        """When project uses dir/index.todo layout, remote changes go to index.todo not a flat file."""
        manager.create_project("myproj")
        manager.create_project("myproj/sub")  # triggers migration to directory layout
        manager.create_group("team")
        manager.get_project_path("myproj").write_text("- [ ] local task\n")
        manager.add_project_to_group("myproj", "team")

        group_dir = manager.shared_dir / "team"
        (group_dir / ".git").mkdir(exist_ok=True)

        # Simulate remote pushing a new task
        shared_file = group_dir / "myproj.todo"
        shared_file.write_text("- [ ] local task\n- [ ] remote task\n")

        with patch("todo.sync.shared_sync.SharedSync.smart_fetch",
                    return_value={"status": "behind", "local_sha": "a", "remote_sha": "b"}), \
             patch("todo.sync.shared_sync.SharedSync.pull", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync.push", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync._commit_all_changes", return_value=True):
            result = manager.sync()

        # Should update the index.todo, not create a flat myproj.todo
        index_path = manager.data_dir / "myproj" / "index.todo"
        flat_path = manager.data_dir / "myproj.todo"
        assert index_path.exists()
        assert not flat_path.exists()
        assert "remote task" in index_path.read_text()

    def test_new_project_from_remote(self, manager):
        """A .todo file in shared/ that doesn't exist in data/ gets created."""
        manager.create_group("team")
        group_dir = manager.shared_dir / "team"
        (group_dir / ".git").mkdir(exist_ok=True)
        reg = manager.load_registry()
        reg["groups"]["team"]["projects"].append("newproj")
        manager.save_registry(reg)

        # Simulate remote having a project we don't have locally
        (group_dir / "newproj.todo").write_text("- [ ] remote only\n")

        with patch("todo.sync.shared_sync.SharedSync.smart_fetch",
                    return_value={"status": "behind", "local_sha": "a", "remote_sha": "b"}), \
             patch("todo.sync.shared_sync.SharedSync.pull", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync.push", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync._commit_all_changes", return_value=True):
            result = manager.sync()

        dst = manager.data_dir / "newproj.todo"
        assert dst.exists()
        assert "remote only" in dst.read_text()

    def test_data_changes_pushed_to_shared(self, manager):
        """Local data/ edits propagate to shared/ even when remote is up_to_date."""
        self._setup_group_with_git(manager)

        # Edit data locally
        manager.get_project_path("proj").write_text("- [ ] edited locally\n")

        with patch("todo.sync.shared_sync.SharedSync.smart_fetch",
                    return_value={"status": "up_to_date", "local_sha": "a", "remote_sha": "a"}), \
             patch("todo.sync.shared_sync.SharedSync.push", return_value=True), \
             patch("todo.sync.shared_sync.SharedSync._commit_all_changes", return_value=True):
            result = manager.sync()

        shared_file = manager.shared_dir / "team" / "proj.todo"
        assert "edited locally" in shared_file.read_text()


class TestNestedSubprojects:
    """Test nested subproject support with '/' in project names."""

    def test_create_nested_project(self, manager):
        path = manager.create_project("myproject")
        sub_path = manager.create_project("myproject/backend")
        assert sub_path.exists()
        assert sub_path.name == "backend.todo"
        reg = manager.load_registry()
        assert "myproject/backend" in reg["projects"]

    def test_auto_migrate_parent_to_directory(self, manager):
        """Creating a subproject auto-migrates parent flat file to dir/index.todo."""
        parent_path = manager.create_project("myproject")
        parent_path.write_text("- [ ] parent task\n")

        # The flat file should exist
        assert (manager.data_dir / "myproject.todo").exists()

        # Create subproject — should migrate parent
        manager.create_project("myproject/backend")

        # Flat file should be gone, replaced by directory
        assert not (manager.data_dir / "myproject.todo").exists()
        index = manager.data_dir / "myproject" / "index.todo"
        assert index.exists()
        assert "parent task" in index.read_text()

        # Subproject file should exist
        assert (manager.data_dir / "myproject" / "backend.todo").exists()

    def test_get_project_path_resolves_index(self, manager):
        """After migration, get_project_path resolves to index.todo."""
        manager.create_project("myproject")
        (manager.data_dir / "myproject.todo").write_text("- [ ] task\n")
        manager.create_project("myproject/sub")

        path = manager.get_project_path("myproject")
        assert path.name == "index.todo"
        assert "task" in path.read_text()

    def test_get_project_path_flat_file(self, manager):
        """Flat projects still resolve to <name>.todo."""
        manager.create_project("flat")
        path = manager.get_project_path("flat")
        assert path.name == "flat.todo"

    def test_list_projects_includes_nested(self, manager):
        manager.create_project("myproject")
        manager.create_project("myproject/backend")
        manager.create_project("myproject/frontend")
        projects = manager.list_projects()
        names = [p["name"] for p in projects]
        assert "myproject" in names
        assert "myproject/backend" in names
        assert "myproject/frontend" in names

    def test_get_all_project_paths_includes_nested(self, manager):
        manager.create_project("myproject")
        manager.create_project("myproject/backend")
        paths = manager.get_all_project_paths()
        names = [name for name, _ in paths]
        assert "myproject" in names
        assert "myproject/backend" in names

    def test_deeply_nested(self, manager):
        """Support deep nesting like myproject/backend/api."""
        manager.create_project("deep")
        manager.create_project("deep/level1")
        manager.create_project("deep/level1/level2")
        paths = manager.get_all_project_paths()
        names = [name for name, _ in paths]
        assert "deep" in names
        assert "deep/level1" in names
        assert "deep/level1/level2" in names

    def test_add_tasks_to_nested_project(self, manager):
        """Tasks can be added to nested projects."""
        from todo.ui.tasks import parse_tasks_from_file, add_task_to_file
        manager.create_project("proj")
        manager.create_project("proj/sub")
        path = manager.get_project_path("proj/sub")
        add_task_to_file(path, "nested task")
        tasks = parse_tasks_from_file(path, "proj/sub")
        assert len(tasks) == 1
        assert tasks[0].text == "nested task"
        assert tasks[0].project_name == "proj/sub"

    def test_remove_nested_project(self, manager):
        manager.create_project("proj")
        manager.create_project("proj/sub")
        path = manager.get_project_path("proj/sub")
        path.write_text("- [ ] task\n")
        assert manager.remove_project("proj/sub")
        assert not path.exists()
        reg = manager.load_registry()
        assert "proj/sub" not in reg["projects"]

    def test_filesystem_discovery(self, manager):
        """Projects created on filesystem (e.g., via sync) are discovered."""
        # Create a nested file directly on filesystem without registry
        nested_dir = manager.data_dir / "discovered" / "child"
        nested_dir.mkdir(parents=True)
        (nested_dir.parent / "index.todo").write_text("- [ ] parent task\n")
        (nested_dir.parent / "child.todo").write_text("- [ ] child task\n")

        projects = manager.list_projects()
        names = [p["name"] for p in projects]
        assert "discovered" in names
        assert "discovered/child" in names


class TestNuke:

    def test_nuke_removes_everything(self, manager):
        manager.create_project("proj")
        assert manager.home_dir.exists()
        manager.nuke_all(force=True)
        assert not manager.home_dir.exists()
