import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from todo.core.config import TodoConfig
from todo.core.conflict import ConflictManager
from todo.core.manager import TodoManager

try:
    from todo.core.project import TodoProject
except ImportError:
    TodoProject = None


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_home(temp_dir):
    """Mock Path.home() to use temp directory"""
    with patch('pathlib.Path.home') as mock:
        mock.return_value = temp_dir
        yield temp_dir


@pytest.fixture
def config(temp_dir):
    """Create a test TodoConfig"""
    config_path = temp_dir / "config.json"
    return TodoConfig(config_path)


@pytest.fixture
def conflict_manager(temp_dir):
    """Create a test ConflictManager"""
    cache_dir = temp_dir / "cache"
    return ConflictManager(cache_dir)


@pytest.fixture
def project_dir(temp_dir):
    """Create a test project directory"""
    project_dir = temp_dir / "test_project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def project(project_dir, conflict_manager):
    """Create a test TodoProject"""
    return TodoProject(project_dir, conflict_manager)


@pytest.fixture
def manager(mock_home):
    """Create a test TodoManager with mocked home"""
    return TodoManager()