"""Base sync interface and common git functionality"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import os
import subprocess
import socket

from .auth import get_git_auth_env, resolve_token, is_https_url
from .providers import detect_provider, parse_remote_url


class SyncInterface(ABC):
    """Abstract base class for sync implementations"""

    @abstractmethod
    def push(self) -> bool:
        pass

    @abstractmethod
    def pull(self) -> bool:
        pass

    @abstractmethod
    def is_sync_enabled(self) -> bool:
        pass


class GitSyncBase(SyncInterface):
    """Base class for git-based sync implementations"""

    def __init__(self, directory: Path, config):
        self.directory = directory
        self.config = config
        self.git_dir = directory / ".git"

    def _git(self, *args: str, auth_env: Optional[dict] = None) -> subprocess.CompletedProcess:
        """Run a git command in self.directory with optional auth env vars."""
        env = None
        if auth_env:
            env = {**os.environ, **auth_env}
        return subprocess.run(
            ["git", *args],
            cwd=self.directory,
            capture_output=True,
            text=True,
            env=env,
        )

    def is_git_available(self) -> bool:
        """Check if git is available"""
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_device_name(self) -> str:
        """Get or generate device identifier"""
        device_name = self.config.get("device_name")
        if not device_name:
            try:
                device_name = socket.gethostname()
            except Exception:
                device_name = "unknown-device"
            self.config.set("device_name", device_name)
        return device_name

    def _get_remote_url(self) -> Optional[str]:
        """Get the configured remote URL"""
        result = self._git("remote", "get-url", "origin")
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _get_head_sha(self) -> Optional[str]:
        """Get local HEAD commit SHA"""
        result = self._git("rev-parse", "HEAD")
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _get_upstream_sha(self) -> Optional[str]:
        """Get upstream tracking branch SHA after fetch"""
        result = self._git("rev-parse", "@{u}")
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _get_merge_base(self) -> Optional[str]:
        """Get merge base between HEAD and upstream"""
        result = self._git("merge-base", "HEAD", "@{u}")
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _has_uncommitted_changes(self) -> bool:
        """Check if working tree has uncommitted changes"""
        result = self._git("status", "--porcelain")
        return bool(result.stdout.strip()) if result.returncode == 0 else False

    def _get_auth_env(self) -> dict:
        """Get auth env vars for the configured remote"""
        remote_url = self._get_remote_url()
        if not remote_url or not is_https_url(remote_url):
            return {"GIT_TERMINAL_PROMPT": "0"}
        host, _, _ = parse_remote_url(remote_url)
        provider = "github" if host == "github.com" else "gitlab" if "gitlab" in (host or "") else None
        if provider:
            token = resolve_token(provider, self.config, interactive=False)
            if token:
                return get_git_auth_env(token, remote_url)
        return {"GIT_TERMINAL_PROMPT": "0"}

    def smart_fetch(self) -> dict:
        """Fetch from remote and compare refs to determine sync action needed.

        Returns dict with:
            'status': 'up_to_date' | 'behind' | 'ahead' | 'diverged' | 'error'
            'local_sha': str
            'remote_sha': str
        """
        if not self.git_dir.exists():
            return {"status": "error", "local_sha": None, "remote_sha": None}

        auth = self._get_auth_env()

        # Fetch latest from remote
        result = self._git("fetch", "origin", auth_env=auth)
        if result.returncode != 0:
            return {"status": "error", "local_sha": None, "remote_sha": None}

        local_sha = self._get_head_sha()
        upstream_sha = self._get_upstream_sha()

        if not local_sha or not upstream_sha:
            return {"status": "error", "local_sha": local_sha, "remote_sha": upstream_sha}

        if local_sha == upstream_sha:
            return {"status": "up_to_date", "local_sha": local_sha, "remote_sha": upstream_sha}

        merge_base = self._get_merge_base()

        if merge_base == local_sha:
            return {"status": "behind", "local_sha": local_sha, "remote_sha": upstream_sha}
        elif merge_base == upstream_sha:
            return {"status": "ahead", "local_sha": local_sha, "remote_sha": upstream_sha}
        else:
            return {"status": "diverged", "local_sha": local_sha, "remote_sha": upstream_sha}

    def _configure_git(self):
        """Configure git user if not already configured"""
        name_result = self._git("config", "user.name")
        email_result = self._git("config", "user.email")
        if name_result.returncode != 0 or email_result.returncode != 0:
            device_name = self.get_device_name()
            self._git("config", "user.name", f"Todo on {device_name}")
            self._git("config", "user.email", f"todo@{device_name}")

    def _commit_all_changes(self, message: str) -> bool:
        """Commit all current changes"""
        try:
            add_result = self._git("add", ".")
            if add_result.returncode != 0:
                return False

            diff_result = self._git("diff", "--staged", "--quiet")

            if diff_result.returncode != 0:
                device_name = self.get_device_name()
                full_message = f"{message} from {device_name} at {datetime.now().isoformat()}"
                commit_result = self._git("commit", "-m", full_message)
                return commit_result.returncode == 0
            return False
        except subprocess.CalledProcessError:
            return False
