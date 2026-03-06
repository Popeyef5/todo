import pytest
from pathlib import Path
from unittest.mock import patch

from todo.core.project import TodoProject
from todo.core.config import TodoConfig


class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_malformed_project_json(self, temp_dir):
        """Test handling of malformed .todo.json"""
        project_dir = temp_dir / "test_project"
        project_dir.mkdir()
        
        todo_file = project_dir / ".todo.json"
        todo_file.write_text("invalid json {")
        
        # Should create project with defaults
        project = TodoProject(project_dir)
        assert project.project_data["name"] == "test_project"
    
    def test_missing_todo_files(self, project, temp_dir):
        """Test handling of missing todo files during pull"""
        # Add non-existent todo to tracking
        project.project_data["todos"]["missing.todo"] = {"created": "2025-01-01"}
        
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        conflicts = project.pull_to_global(config)
        
        # Should complete without errors
        assert len(conflicts) == 0
    
    def test_empty_global_todo_push(self, project):
        """Test pushing from empty global.todo"""
        # Create empty global.todo
        project.global_todo.write_text("")
        
        conflicts = project.push_from_global()
        assert len(conflicts) == 0
    
    def test_deeply_nested_todos(self, project):
        """Test very deeply nested todo structure"""
        deep_path = "a.very.deeply.nested.todo.structure.that.goes.many.levels.deep"
        todo_file = project.add_todo(deep_path)
        
        assert todo_file.exists()
        expected_path = "a/very/deeply/nested/todo/structure/that/goes/many/levels/deep.todo"
        assert expected_path in project.project_data["todos"]
    
    def test_unicode_in_todo_content(self, project, temp_dir):
        """Test handling of unicode content in todos"""
        todo_file = project.add_todo("unicode.test")
        unicode_content = "# TODO: Unicode Test\n\n✅ Task 1\n🔥 Urgent task\n📋 Notes with émojis"
        todo_file.write_text(unicode_content, encoding='utf-8')
        
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        conflicts = project.pull_to_global(config)
        
        assert len(conflicts) == 0
        global_content = project.global_todo.read_text()
        assert "✅ Task 1" in global_content
        assert "🔥 Urgent task" in global_content
    
    def test_large_todo_files(self, project, temp_dir):
        """Test handling of large todo files"""
        todo_file = project.add_todo("large.test")
        
        # Create a large todo file (simulate ~1MB of content)
        large_content = "# Large TODO File\n\n"
        large_content += "- [ ] Task {}\n".format("x" * 100) * 1000
        todo_file.write_text(large_content)
        
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        conflicts = project.pull_to_global(config)
        
        assert len(conflicts) == 0
        assert project.global_todo.exists()
    
    def test_special_characters_in_filenames(self, project):
        """Test handling of special characters in todo names"""
        # Test various special characters that should be handled
        special_names = [
            "api-v2.endpoints",
            "user_auth.system", 
            "mobile@v1.features"
        ]
        
        for name in special_names:
            todo_file = project.add_todo(name)
            assert todo_file.exists()
            # Convert dots to slashes, keep other special chars
            expected_path = name.replace('.', '/') + '.todo'
            assert expected_path in project.project_data["todos"]
    
    def test_concurrent_access_simulation(self, project, temp_dir):
        """Test simulated concurrent access to project files"""
        # Simulate what happens if two processes modify the same project
        todo_file = project.add_todo("concurrent.test")
        todo_file.write_text("# Original content")
        
        # First process pulls to global
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        project.pull_to_global(config)
        
        # Simulate second process modifying the file
        todo_file.write_text("# Modified by second process")
        
        # First process tries to push from global
        conflicts = project.push_from_global()
        
        # Should detect conflict or handle gracefully
        # (This test mainly ensures no crashes occur)
        assert isinstance(conflicts, list)
    
    def test_symlink_handling_fallback(self, manager, temp_dir):
        """Test symlink creation fallback when symlinks not supported"""
        project_dir = temp_dir / "test_project"
        project_dir.mkdir()
        
        project = manager.init_project(project_dir)
        todo_file = project.add_todo("test.feature")
        
        # Mock symlink to fail (simulate Windows or restricted filesystem)
        original_symlink = Path.symlink_to
        
        def mock_symlink_fail(self, target):
            raise OSError("Symlinks not supported")
        
        with patch.object(Path, 'symlink_to', mock_symlink_fail):
            # Should fall back to copying
            manager.update_project_links(project)
            
            # Check that some form of link/copy was created
            project_id = project.project_data["id"]
            links_dir = manager.links_dir / project_id
            assert links_dir.exists()
    
    def test_corrupted_registry_recovery(self, manager):
        """Test recovery from corrupted registry file"""
        # Corrupt the registry file
        manager.registry_file.write_text("invalid json {")
        
        # Should recover with default registry
        registry = manager.load_registry()
        assert "projects" in registry
        assert isinstance(registry["projects"], dict)
    
    def test_missing_cache_directory_creation(self, temp_dir):
        """Test cache directory creation when missing"""
        from todo.core.conflict import ConflictManager
        
        cache_dir = temp_dir / "missing_cache"
        # Don't create the directory
        
        # Should create cache directory automatically
        conflict_manager = ConflictManager(cache_dir)
        assert cache_dir.exists()
        
        # Should be able to use checksums
        checksums = {"test": "hash"}
        conflict_manager.save_checksums(checksums)
        loaded = conflict_manager.load_checksums()
        assert loaded == checksums