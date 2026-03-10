"""Git sync for the main ~/.todo/ repository"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .auth import get_git_auth_env, resolve_token, is_https_url
from .base import GitSyncBase
from .providers import parse_remote_url


class MainSync(GitSyncBase):
    """Git sync for the main ~/.todo/ repository"""

    def __init__(self, home_dir: Path, config):
        super().__init__(home_dir, config)

    def _auth_env_for_url(self, remote_url: str) -> dict:
        """Build auth env vars directly from a remote URL (before remote is configured)."""
        if not is_https_url(remote_url):
            return {"GIT_TERMINAL_PROMPT": "0"}
        host, _, _ = parse_remote_url(remote_url)
        provider = "github" if host == "github.com" else "gitlab" if "gitlab" in (host or "") else None
        if not provider:
            return {"GIT_TERMINAL_PROMPT": "0"}
        token = resolve_token(provider, self.config, interactive=False)
        if not token:
            return {"GIT_TERMINAL_PROMPT": "0"}
        return get_git_auth_env(token, remote_url)

    def setup(self, remote_url: str, clone: bool = False) -> str:
        """Initialize git repo and configure remote. If clone=True, clone from remote first.

        Returns None on success, or an error message string on failure.
        """
        if not self.is_git_available():
            return "git is not installed or not found in PATH"

        if clone:
            # ~/.todo/ may already exist with files from ensure_structure().
            # git clone refuses non-empty dirs, so clone into a temp dir
            # and move the result over. This lets git handle all branch
            # tracking setup natively.
            auth = self._auth_env_for_url(remote_url)
            env = {**os.environ, **auth}

            with tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(
                    ["git", "clone", remote_url, tmp],
                    capture_output=True, text=True, env=env,
                )
                if result.returncode != 0:
                    stderr = result.stderr.strip()
                    return f"git clone failed: {stderr}"

                tmp_path = Path(tmp)

                # Remove existing .git if any (from a prior failed setup)
                if self.git_dir.exists():
                    shutil.rmtree(self.git_dir)

                # Move cloned .git into our directory
                shutil.move(str(tmp_path / ".git"), str(self.git_dir))

                # Copy repo files over (overwrite local scaffolding)
                for item in tmp_path.iterdir():
                    dest = self.directory / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))

            self._configure_git()
            self.config.set("sync_enabled", True)
            self.config.set("sync_remote", remote_url)
            return None

        # Init new repo
        if not self.git_dir.exists():
            self._git("init")

            # Create .gitignore
            gitignore = self.directory / ".gitignore"
            gitignore.write_text("shared/\n.stage.json\n")

        self._configure_git()

        # Set remote
        result = self._git("remote", "add", "origin", remote_url)
        if result.returncode != 0:
            # Remote may already exist, update it
            self._git("remote", "set-url", "origin", remote_url)

        # Initial commit + push
        self._commit_all_changes("initial setup")
        pushed = self.push()
        if not pushed:
            return "initial push failed — check your URL and credentials"

        self.config.set("sync_enabled", True)
        self.config.set("sync_remote", remote_url)
        return None

    def push(self) -> bool:
        """Push to remote"""
        if not self.git_dir.exists():
            return False
        result = self._git("push", "-u", "origin", "HEAD", auth_env=self._get_auth_env())
        return result.returncode == 0

    def pull(self) -> bool:
        """Pull from remote"""
        if not self.git_dir.exists():
            return False
        result = self._git("pull", "--rebase", "origin", "HEAD", auth_env=self._get_auth_env())
        return result.returncode == 0

    def full_sync(self) -> dict:
        """Smart sync: commit, fetch+compare, pull if behind, push if ahead.

        Returns dict with 'status' and 'pulled' and 'pushed' keys.
        """
        self._commit_all_changes("sync")

        fetch_result = self.smart_fetch()
        status = fetch_result["status"]
        pulled = False
        pushed = False

        if status == "behind" or status == "diverged":
            pulled = self.pull()

        if status != "error":
            pushed = self.push()

        return {"status": status, "pulled": pulled, "pushed": pushed}

    def is_sync_enabled(self) -> bool:
        """Check if main sync is enabled"""
        return self.config.get("sync_enabled", False) and self.git_dir.exists()

    def get_sync_status(self) -> dict:
        """Get current sync status"""
        status = {
            "enabled": self.is_sync_enabled(),
            "has_remote": False,
            "remote_url": None,
        }
        if self.git_dir.exists():
            result = self._git("remote", "get-url", "origin")
            if result.returncode == 0:
                status["has_remote"] = True
                status["remote_url"] = result.stdout.strip()
        return status
