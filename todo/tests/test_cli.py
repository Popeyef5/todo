import pytest
import sys
from unittest.mock import patch, MagicMock
from io import StringIO

from todo.cli import main


class TestCLI:
    """Test CLI functionality"""
    
    @patch('todo.cli.TodoManager')
    def test_init_command(self, mock_manager_class):
        """Test init command"""
        mock_manager = MagicMock()
        mock_project = MagicMock()
        mock_project.project_dir = "/test/project"
        mock_project.project_data = {"id": "test_project"}
        mock_manager.init_project.return_value = mock_project
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'init']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
                mock_print.assert_any_call("Initialized Todo project in /test/project")
                mock_print.assert_any_call("Project ID: test_project")
    
    @patch('todo.cli.TodoManager')
    def test_add_command(self, mock_manager_class):
        """Test add command"""
        mock_manager = MagicMock()
        mock_project = MagicMock()
        mock_project.add_todo.return_value = "/test/project/feature.todo"
        mock_project.pull_to_global.return_value = []
        mock_manager.get_project.return_value = mock_project
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'add', 'feature.test']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
                mock_print.assert_any_call("Created todo: /test/project/feature.todo")
    
    @patch('todo.cli.TodoManager')
    def test_add_command_no_project(self, mock_manager_class):
        """Test add command with no project"""
        mock_manager = MagicMock()
        mock_manager.get_project.return_value = None
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'add', 'feature.test']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                with pytest.raises(SystemExit):
                    main()
                mock_print.assert_any_call("No Todo project found. Run 'todo init' first.")
    
    @patch('todo.cli.TodoManager')
    def test_list_command(self, mock_manager_class):
        """Test list command"""
        mock_manager = MagicMock()
        mock_registry = {
            "projects": {
                "project1": {
                    "name": "Test Project 1",
                    "path": "/path/to/project1"
                },
                "project2": {
                    "name": "Test Project 2", 
                    "path": "/path/to/project2"
                }
            }
        }
        mock_manager.load_registry.return_value = mock_registry
        mock_manager.links_dir = MagicMock()
        mock_manager.links_dir.__truediv__ = lambda self, x: MagicMock()
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'list']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
                mock_print.assert_any_call("Tracked projects:")
    
    @patch('todo.cli.TodoManager')
    def test_edit_target_command(self, mock_manager_class):
        """Test editing a target (non-subcommand)"""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'myproject']
        with patch.object(sys, 'argv', test_args):
            main()
            mock_manager.launch_editor.assert_called_once_with('myproject')
    
    @patch('todo.cli.TodoManager')
    def test_edit_no_args(self, mock_manager_class):
        """Test editing with no arguments"""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo']
        with patch.object(sys, 'argv', test_args):
            main()
            mock_manager.launch_editor.assert_called_once_with()
    
    @patch('todo.cli.TodoManager')
    def test_sync_status_command(self, mock_manager_class):
        """Test sync status command"""
        mock_manager = MagicMock()
        mock_manager.master_sync.get_sync_status.return_value = {"status": "disabled"}
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'sync', 'status']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
                mock_print.assert_any_call("Sync is not enabled. Use 'todo sync setup <remote-url>' to get started.")
    
    @patch('todo.cli.TodoManager')
    def test_config_command(self, mock_manager_class):
        """Test config command"""
        mock_manager = MagicMock()
        mock_manager.config.config = {
            "editor": "nvim",
            "max_depth": 2,
            "toc_enabled": True
        }
        mock_manager_class.return_value = mock_manager
        
        test_args = ['todo', 'config']
        with patch.object(sys, 'argv', test_args):
            with patch('builtins.print') as mock_print:
                main()
                mock_print.assert_any_call("Current configuration:")