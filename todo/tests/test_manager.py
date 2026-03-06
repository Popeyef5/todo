import pytest
from pathlib import Path
from unittest.mock import patch

from todo.core.manager import TodoManager


class TestTodoManager:
    """Test TodoManager functionality"""
    
    def test_manager_initialization(self, manager):
        """Test TodoManager initialization"""
        assert manager.home_dir.exists()
        assert manager.links_dir.exists()
        assert manager.cache_dir.exists()
        assert (manager.home_dir / "README.md").exists()
    
    def test_project_registration(self, manager, temp_dir):
        """Test registering a project"""
        project_dir = temp_dir / "test_project"
        project_dir.mkdir()
        
        project = manager.init_project(project_dir)
        registry = manager.load_registry()
        
        project_id = project.project_data["id"]
        assert project_id in registry["projects"]
        assert registry["projects"][project_id]["path"] == str(project_dir)
    
    def test_project_removal(self, manager, temp_dir):
        """Test removing a project from tracking"""
        project_dir = temp_dir / "test_project"
        project_dir.mkdir()
        
        # Register project first
        project = manager.init_project(project_dir)
        project_id = project.project_data["id"]
        
        # Remove project
        success = manager.remove_project(project_id)
        
        assert success is True
        registry = manager.load_registry()
        assert project_id not in registry["projects"]
