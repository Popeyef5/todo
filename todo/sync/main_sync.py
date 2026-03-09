"""Git sync for the main ~/.todo/ repository"""

import os
import subprocess
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

    def setup(self, remote_url: str, clone: bool = False) -> bool:
        """Initialize git repo and configure remote. If clone=True, clone from remote first."""
        if not self.is_git_available():
            return False

        if clone:
            try:
                auth = self._auth_env_for_url(remote_url)
                env = {**os.environ, **auth}
                subprocess.run(
                    ["git", "clone", remote_url, str(self.directory)],
                    capture_output=True, check=True, env=env,
                )
                self._configure_git()
                return True
            except subprocess.CalledProcessError:
                return False

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
        self.push()

        self.config.set("sync_enabled", True)
        self.config.set("sync_remote", remote_url)
        return True

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
