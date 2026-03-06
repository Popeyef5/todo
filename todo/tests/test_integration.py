import pytest
from pathlib import Path
from unittest.mock import patch

from todo.core.manager import TodoManager


class TestIntegration:
    """Integration tests for complete workflows"""
    
    def test_full_workflow(self, mock_home):
        """Test complete workflow: init -> add -> pull -> push"""
        manager = TodoManager()
        
        # Create test projects
        project1_dir = mock_home / "project1"
        project2_dir = mock_home / "project2"
        project1_dir.mkdir()
        project2_dir.mkdir()
        
        # Initialize projects
        project1 = manager.init_project(project1_dir)
        project2 = manager.init_project(project2_dir)
        
        # Add todos to projects
        project1.add_todo("frontend.login")
        project1.add_todo("backend.api")
        project2.add_todo("docs.readme")
        
        # Pull to project globals
        project1.pull_to_global(manager.config)
        project2.pull_to_global(manager.config)
        
        # Pull to central global
        conflicts = manager.pull_global()
        assert len(conflicts) == 0
        
        # Check central global.todo exists and has content
        assert manager.global_todo.exists()
        global_content = manager.global_todo.read_text()
        assert "frontend/login.todo" in global_content
        assert "docs/readme.todo" in global_content