import pytest
import json
from pathlib import Path

from todo.core.config import TodoConfig


class TestTodoConfig:
    """Test TodoConfig class"""
    
    def test_default_config_creation(self, temp_dir):
        """Test that default config is created properly"""
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        
        assert config.get("editor") == "nvim"
        assert config.get("max_depth") == 2
        assert config.get("toc_enabled") is True
        assert config.get("toc_mode") == "anchors"
    
    def test_config_persistence(self, temp_dir):
        """Test that config is saved and loaded correctly"""
        config_path = temp_dir / "config.json"
        config = TodoConfig(config_path)
        
        config.set("editor", "vim")
        config.set("max_depth", 5)
        
        # Create new config instance to test loading
        new_config = TodoConfig(config_path)
        assert new_config.get("editor") == "vim"
        assert new_config.get("max_depth") == 5
    
    def test_config_file_corruption_handling(self, temp_dir):
        """Test handling of corrupted config files"""
        config_path = temp_dir / "config.json"
        
        # Write invalid JSON
        config_path.write_text("invalid json {")
        
        # Should fall back to defaults
        config = TodoConfig(config_path)
        assert config.get("editor") == "nvim"