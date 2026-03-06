import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from todo.sync.master_sync import MasterSync
from todo.sync.group_sync import GroupSync
from todo.core.manager import TodoManager


class TestMasterSync:
    """Test MasterSync functionality"""
    
    def test_git_availability_check(self, manager):
        """Test checking if git is available"""
        master_sync = manager.master_sync
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock()
            assert master_sync.is_git_available() is True
            
        with patch('subprocess.run', side_effect=FileNotFoundError):
            assert master_sync.is_git_available() is False
    
    def test_device_name_generation(self, manager):
        """Test device name generation and caching"""
        master_sync = manager.master_sync
        
        # First call should generate and cache
        device_name = master_sync.get_device_name()
        assert device_name is not None
        assert manager.config.get('device_name') == device_name
        
        # Second call should return cached value
        assert master_sync.get_device_name() == device_name
    
    def test_sync_enabled_check(self, manager):
        """Test sync enabled checking"""
        master_sync = manager.master_sync
        
        # Initially should be disabled
        assert master_sync.is_sync_enabled() is False
        
        # Enable sync config
        manager.config.set('sync_enabled', True)
        manager.config.set('sync_remote', 'git@github.com:user/test.git')
        
        # Still disabled without git directory
        assert master_sync.is_sync_enabled() is False
        
        # Create git directory
        git_dir = manager.home_dir / ".git"
        git_dir.mkdir()
        
        # Now should be enabled
        assert master_sync.is_sync_enabled() is True
    
    @patch('subprocess.run')
    def test_master_sync_pull(self, mock_subprocess, manager):
        """Test git pull functionality"""
        master_sync = manager.master_sync
        
        # Setup sync as enabled
        manager.config.set('sync_enabled', True)
        manager.config.set('sync_remote', 'git@github.com:user/test.git')
        git_dir = manager.home_dir / ".git"
        git_dir.mkdir()
        
        # Mock successful git pull
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        result = master_sync.sync_pull()
        assert result is True
        mock_subprocess.assert_called_with(
            ['git', 'pull', '--rebase'],
            cwd=manager.home_dir,
            check=True,
            capture_output=True
        )
    
    @patch('subprocess.run')
    def test_master_sync_push(self, mock_subprocess, manager):
        """Test git push functionality"""
        master_sync = manager.master_sync
        
        # Setup sync as enabled
        manager.config.set('sync_enabled', True)
        manager.config.set('sync_remote', 'git@github.com:user/test.git')
        git_dir = manager.home_dir / ".git"
        git_dir.mkdir()
        
        # Mock git commands
        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd == ['git', 'add', '.']:
                return MagicMock(returncode=0)
            elif cmd == ['git', 'diff', '--staged', '--quiet']:
                return MagicMock(returncode=1)  # Changes exist
            elif cmd[0:2] == ['git', 'commit']:
                return MagicMock(returncode=0)
            elif cmd == ['git', 'push']:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)
        
        mock_subprocess.side_effect = mock_run_side_effect
        
        result = master_sync.sync_push()
        assert result is True
    
    def test_get_sync_status_disabled(self, manager):
        """Test sync status when disabled"""
        master_sync = manager.master_sync
        status = master_sync.get_sync_status()
        
        assert status["status"] == "disabled"
    
    @patch('subprocess.run')
    def test_get_sync_status_enabled(self, mock_subprocess, manager):
        """Test sync status when enabled"""
        master_sync = manager.master_sync
        
        # Setup sync as enabled
        manager.config.set('sync_enabled', True)
        manager.config.set('sync_remote', 'git@github.com:user/test.git')
        git_dir = manager.home_dir / ".git"
        git_dir.mkdir()
        
        # Mock git status commands
        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd == ['git', 'status', '--porcelain']:
                return MagicMock(returncode=0, stdout="")  # No uncommitted changes
            elif cmd == ['git', 'log', 'origin/main..HEAD', '--oneline']:
                return MagicMock(returncode=0, stdout="")  # No unpushed commits
            elif cmd == ['git', 'log', '-1', '--format=%ci']:
                return MagicMock(returncode=0, stdout="2025-01-20 15:30:00 +0000")
            return MagicMock(returncode=0)
        
        mock_subprocess.side_effect = mock_run_side_effect
        
        status = master_sync.get_sync_status()
        
        assert status["status"] == "enabled"
        assert status["remote"] == "git@github.com:user/test.git"
        assert status["uncommitted_changes"] is False
        assert status["unpushed_commits"] is False
        assert "2025-01-20" in status["last_sync"]