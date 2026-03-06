from pathlib import Path
from typing import Dict
import json
from datetime import datetime


class TodoConfig:
    """Configuration management for Todo"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.default_config = {
            "editor": "nvim",
            "auto_sync_on_edit": True,
            "sync_enabled": False,
            "sync_remote": None,
            "sync_auto": True,
            "device_name": None,
            "github_token": None,
            "gitlab_token": None,
            "gitlab_host": None,
            "sync_provider": None,      # "github", "gitlab", or None (auto-detect)
            "sync_interval": 60,        # background sync check interval in seconds
        }
        self.config = self.load_config()
    
    def load_config(self) -> Dict:
        """Load configuration from file or create default"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                return {**self.default_config, **config}
            except (json.JSONDecodeError, IOError):
                pass
        return self.default_config.copy()
    
    def save_config(self):
        """Save current configuration to file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
        # Restrict permissions since config may contain tokens
        try:
            import os
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass
    
    def get(self, key: str, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value):
        """Set configuration value"""
        self.config[key] = value
        self.save_config()