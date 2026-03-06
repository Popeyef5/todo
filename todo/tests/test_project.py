import pytest
from pathlib import Path

from todo.core.project import TodoProject
from todo.core.config import TodoConfig


class TestTodoProject:
    """Test TodoProject functionality"""
    
    def test_project_initialization(self, project):
        """Test project initialization"""
        assert project.project_data["name"] == "test_project"
        assert "created" in project.project_data
        assert project.project_data["todos"] == {}
    
    def test_add_todo_dot_notation(self, project):
        """Test adding todo with dot notation"""
        todo_path = project.add_todo("app.feature.login")
        
        expected_path = project.project_dir / "app" / "feature" / "login.todo"
        assert todo_path == expected_path
        assert expected_path.exists()
        assert "app/feature/login.todo" in project.project_data["todos"]
    
    def test_scan_todos(self, project):
        """Test scanning for existing todo files"""
        # Create some todo files
        (project.project_dir / "existing.todo").write_text("# Existing todo")
        subdir = project.project_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.todo").write_text("# Nested todo")
        
        found = project.scan_todos(max_depth=2)
        
        assert len(found) == 2
        assert "existing.todo" in project.project_data["todos"]
        assert "subdir/nested.todo" in project.project_data["todos"]
    
    def test_pull_to_global(self, project, temp_dir):
        """Test pulling individual todos to global.todo"""
        # Create some todo files
        todo1 = project.project_dir / "todo1.todo"
        todo2 = project.project_dir / "subdir" / "todo2.todo"
        todo1.write_text("# Todo 1\nSome content")
        todo2.parent.mkdir()
        todo2.write_text("# Todo 2\nOther content")
        
        # Add to project tracking
        project.project_data["todos"]["todo1.todo"] = {"created": "2025-01-01"}
        project.project_data["todos"]["subdir/todo2.todo"] = {"created": "2025-01-01"}
        
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        config.config["toc_enabled"] = False  # Simplify test
        
        conflicts = project.pull_to_global(config)
        
        assert len(conflicts) == 0
        assert project.global_todo.exists()
        
        global_content = project.global_todo.read_text()
        assert "## todo1.todo" in global_content
        assert "## subdir/todo2.todo" in global_content
        assert "<!-- BEGIN todo1.todo -->" in global_content