import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from todo.core.config import TodoConfig
from todo.core.conflict import ConflictManager
from todo.core.manager import TodoManager


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d)


@pytest.fixture
def mock_home(temp_dir):
    """Mock Path.home() to use temp directory"""
    with patch('pathlib.Path.home') as mock:
        mock.return_value = temp_dir
        yield temp_dir


@pytest.fixture
def config(temp_dir):
    """Create a test TodoConfig"""
    return TodoConfig(temp_dir / "config.json")


@pytest.fixture
def conflict_manager(temp_dir):
    """Create a test ConflictManager"""
    return ConflictManager(temp_dir / "cache")


@pytest.fixture
def manager(mock_home):
    """Create a test TodoManager with mocked home"""
    return TodoManager()
