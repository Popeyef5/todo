"""Tests for sync setup with existing repos (clone into pre-existing directory)."""

import subprocess
import shutil
import tempfile
import pytest
from pathlib import Path

from todo.core.config import TodoConfig
from todo.sync.main_sync import MainSync
from todo.sync.shared_sync import SharedSync


@pytest.fixture
def bare_remote():
    """Create a bare git repo with a commit, simulating an existing remote."""
    d = Path(tempfile.mkdtemp())
    bare = d / "remote.git"
    work = d / "workdir"

    # Create bare repo
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)

    # Clone it, add a commit, push
    subprocess.run(["git", "clone", str(bare), str(work)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=work, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=work, capture_output=True)
    (work / "data" / "myproject.todo").parent.mkdir(parents=True)
    (work / "data" / "myproject.todo").write_text("- [ ] synced task\n")
    subprocess.run(["git", "add", "."], cwd=work, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=work, capture_output=True, check=True)
    subprocess.run(["git", "push", "origin", "HEAD"], cwd=work, capture_output=True, check=True)

    yield bare

    shutil.rmtree(d)


class TestMainSyncCloneExistingDir:
    """Test that clone works when ~/.todo/ already exists with subdirectories."""

    def test_clone_into_preexisting_directory(self, bare_remote, temp_dir):
        """Simulates: user opens interactive mode (creates ~/.todo/), then sets up with existing repo."""
        home_dir = temp_dir / ".todo"
        home_dir.mkdir()
        # Simulate ensure_structure() creating subdirs before setup
        (home_dir / "data").mkdir()
        (home_dir / "shared").mkdir()
        (home_dir / "cache").mkdir()

        config = TodoConfig(home_dir / "config.json")
        sync = MainSync(home_dir, config)

        result = sync.setup(str(bare_remote), clone=True)

        assert result is True

    def test_clone_sets_upstream_tracking(self, bare_remote, temp_dir):
        """After clone, @{u} should resolve (upstream tracking is set)."""
        home_dir = temp_dir / ".todo"
        home_dir.mkdir()
        (home_dir / "data").mkdir()
        (home_dir / "shared").mkdir()

        config = TodoConfig(home_dir / "config.json")
        sync = MainSync(home_dir, config)
        sync.setup(str(bare_remote), clone=True)

        # This is the exact call that was failing before the fix
        result = subprocess.run(
            ["git", "rev-parse", "@{u}"],
            cwd=home_dir, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Upstream not set: {result.stderr}"

    def test_clone_fetches_remote_content(self, bare_remote, temp_dir):
        """Files from the remote repo should be present after clone."""
        home_dir = temp_dir / ".todo"
        home_dir.mkdir()
        (home_dir / "data").mkdir()

        config = TodoConfig(home_dir / "config.json")
        sync = MainSync(home_dir, config)
        sync.setup(str(bare_remote), clone=True)

        assert (home_dir / "data" / "myproject.todo").exists()
        assert "synced task" in (home_dir / "data" / "myproject.todo").read_text()

    def test_clone_enables_sync_in_config(self, bare_remote, temp_dir):
        """sync_enabled and sync_remote should be set after clone."""
        home_dir = temp_dir / ".todo"
        home_dir.mkdir()

        config = TodoConfig(home_dir / "config.json")
        sync = MainSync(home_dir, config)
        sync.setup(str(bare_remote), clone=True)

        assert config.get("sync_enabled") is True
        assert config.get("sync_remote") == str(bare_remote)

    def test_full_sync_works_after_clone(self, bare_remote, temp_dir):
        """After clone, full_sync (which uses @{u}) should not error."""
        home_dir = temp_dir / ".todo"
        home_dir.mkdir()
        (home_dir / "data").mkdir()

        config = TodoConfig(home_dir / "config.json")
        sync = MainSync(home_dir, config)
        sync.setup(str(bare_remote), clone=True)

        result = sync.full_sync()
        assert result["status"] != "error"


class TestSharedSyncCloneExistingDir:
    """Test that SharedSync.clone works when the group dir already exists."""

    def test_clone_into_preexisting_directory(self, bare_remote, temp_dir):
        group_dir = temp_dir / "shared" / "team"
        group_dir.mkdir(parents=True)

        config = TodoConfig(temp_dir / "config.json")
        sync = SharedSync(group_dir, config)

        result = sync.clone(str(bare_remote))
        assert result is True

    def test_clone_sets_upstream_tracking(self, bare_remote, temp_dir):
        group_dir = temp_dir / "shared" / "team"
        group_dir.mkdir(parents=True)

        config = TodoConfig(temp_dir / "config.json")
        sync = SharedSync(group_dir, config)
        sync.clone(str(bare_remote))

        result = subprocess.run(
            ["git", "rev-parse", "@{u}"],
            cwd=group_dir, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Upstream not set: {result.stderr}"
