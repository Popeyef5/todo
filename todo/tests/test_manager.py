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


class TestNuke:

    def test_nuke_removes_everything(self, manager):
        manager.create_project("proj")
        assert manager.home_dir.exists()
        manager.nuke_all(force=True)
        assert not manager.home_dir.exists()
