"""Git sync for a shared group repository in shared/<group>/"""

import os
from pathlib import Path

from .auth import get_git_auth_env, resolve_token, is_https_url
from .base import GitSyncBase
from .providers import parse_remote_url


class SharedSync(GitSyncBase):
    """Git sync for a shared group repository in shared/<group>/"""

    def __init__(self, group_dir: Path, config):
        super().__init__(group_dir, config)
        self.group_name = group_dir.name

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

    def setup(self, remote_url: str) -> bool:
        """Init git repo and set remote"""
        if not self.is_git_available():
            return False

        self.directory.mkdir(parents=True, exist_ok=True)

        if not self.git_dir.exists():
            self._git("init")

        self._configure_git()

        result = self._git("remote", "add", "origin", remote_url)
        if result.returncode != 0:
            self._git("remote", "set-url", "origin", remote_url)

        self._commit_all_changes("initial setup")
        self.push()
        return True

    def clone(self, remote_url: str) -> bool:
        """Clone a shared group repo into a possibly pre-existing directory"""
        if not self.is_git_available():
            return False

        self.directory.mkdir(parents=True, exist_ok=True)

        if not self.git_dir.exists():
            self._git("init")

        self._configure_git()

        result = self._git("remote", "add", "origin", remote_url)
        if result.returncode != 0:
            self._git("remote", "set-url", "origin", remote_url)

        auth_env = self._auth_env_for_url(remote_url)
        result = self._git("fetch", "origin", auth_env=auth_env)
        if result.returncode != 0:
            return False

        result = self._git("symbolic-ref", "refs/remotes/origin/HEAD")
        if result.returncode == 0:
            default_branch = result.stdout.strip().replace("refs/remotes/origin/", "")
        else:
            default_branch = "main"
            check = self._git("rev-parse", "--verify", "origin/main")
            if check.returncode != 0:
                default_branch = "master"

        result = self._git("checkout", "-B", default_branch, f"origin/{default_branch}")
        if result.returncode != 0:
            return False

        self._git("branch", f"--set-upstream-to=origin/{default_branch}")
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
        """Check if this shared group has a remote configured"""
        if not self.git_dir.exists():
            return False
        result = self._git("remote", "get-url", "origin")
        return result.returncode == 0
