import json
import os
import pytest
from todo.core.config import TodoConfig


class TestTodoConfig:

    def test_default_config(self, temp_dir):
        config = TodoConfig(temp_dir / "config.json")
        assert config.get("editor") == "nvim"
        assert config.get("auto_sync_on_edit") is True
        assert config.get("sync_enabled") is False
        assert config.get("sync_remote") is None
        assert config.get("sync_interval") == 60

    def test_get_missing_key_returns_default(self, config):
        assert config.get("nonexistent") is None
        assert config.get("nonexistent", 42) == 42

    def test_set_persists_to_disk(self, temp_dir):
        config = TodoConfig(temp_dir / "config.json")
        config.set("editor", "vim")
        # Reload from disk
        config2 = TodoConfig(temp_dir / "config.json")
        assert config2.get("editor") == "vim"

    def test_set_preserves_other_keys(self, config):
        config.set("editor", "code")
        assert config.get("auto_sync_on_edit") is True

    def test_config_file_permissions(self, temp_dir):
        config = TodoConfig(temp_dir / "config.json")
        config.set("github_token", "secret")
        mode = os.stat(temp_dir / "config.json").st_mode & 0o777
        assert mode == 0o600

    def test_corrupt_config_falls_back_to_defaults(self, temp_dir):
        path = temp_dir / "config.json"
        path.write_text("not valid json{{{")
        config = TodoConfig(path)
        assert config.get("editor") == "nvim"

    def test_merge_with_existing_file(self, temp_dir):
        """Existing config on disk should be merged with defaults"""
        path = temp_dir / "config.json"
        path.write_text(json.dumps({"editor": "emacs"}))
        config = TodoConfig(path)
        assert config.get("editor") == "emacs"
        assert config.get("sync_enabled") is False  # from defaults
