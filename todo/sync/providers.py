"""Git hosting provider abstraction for sync operations"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class GitProvider(ABC):
    """Abstract base class for git hosting providers"""

    @abstractmethod
    def get_latest_sha(self, owner: str, repo: str, branch: str = None) -> Optional[str]:
        """Check remote branch SHA via API for fast change detection.

        Args:
            branch: Branch name to check. If None, uses the remote's default branch.
        """
        pass

    @abstractmethod
    def create_repo(self, name: str, private: bool = True) -> Optional[str]:
        """Create remote repo, return HTTPS clone URL"""
        pass

    @abstractmethod
    def validate_token(self, token: str) -> Optional[str]:
        """Validate token, return username if valid, None otherwise"""
        pass

    @abstractmethod
    def get_https_url(self, owner: str, repo: str) -> str:
        """Return HTTPS clone URL"""
        pass

    @abstractmethod
    def add_collaborator(self, owner: str, repo: str, username: str) -> bool:
        """Invite a user as a collaborator on a repo. Returns True on success."""
        pass


class GitHubProvider(GitProvider):
    """GitHub API provider"""

    API_BASE = "https://api.github.com"

    def __init__(self, token: str):
        self.token = token

    def _request(self, path: str, method: str = "GET", data: dict = None,
                 headers: dict = None) -> Optional[urllib.request.Request]:
        """Make an authenticated API request"""
        url = f"{self.API_BASE}{path}"
        req_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            return urllib.request.urlopen(req, timeout=5)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None

    def get_latest_sha(self, owner: str, repo: str, branch: str = None) -> Optional[str]:
        ref = branch or "HEAD"
        url = f"{self.API_BASE}/repos/{owner}/{repo}/commits/{ref}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.sha",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return resp.read().decode("utf-8").strip()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None

    def create_repo(self, name: str, private: bool = True) -> Optional[str]:
        resp = self._request("/user/repos", method="POST",
                             data={"name": name, "private": private})
        if resp is None:
            return None
        try:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("clone_url")
        except (json.JSONDecodeError, KeyError):
            return None

    def validate_token(self, token: str) -> Optional[str]:
        url = f"{self.API_BASE}/user"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("login")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError):
            return None

    def get_https_url(self, owner: str, repo: str) -> str:
        return f"https://github.com/{owner}/{repo}.git"

    def add_collaborator(self, owner: str, repo: str, username: str) -> bool:
        resp = self._request(
            f"/repos/{owner}/{repo}/collaborators/{username}",
            method="PUT",
            data={"permission": "push"},
        )
        return resp is not None


class GitLabProvider(GitProvider):
    """GitLab API provider"""

    def __init__(self, token: str, host: str = "gitlab.com"):
        self.token = token
        self.host = host
        self.api_base = f"https://{host}/api/v4"

    def _request(self, path: str, method: str = "GET", data: dict = None) -> Optional[object]:
        """Make an authenticated API request"""
        url = f"{self.api_base}{path}"
        headers = {
            "PRIVATE-TOKEN": self.token,
            "Accept": "application/json",
        }

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            return urllib.request.urlopen(req, timeout=5)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None

    def get_latest_sha(self, owner: str, repo: str, branch: str = None) -> Optional[str]:
        project = urllib.parse.quote(f"{owner}/{repo}", safe="")
        ref = branch or "HEAD"
        resp = self._request(
            f"/projects/{project}/repository/commits?ref_name={urllib.parse.quote(ref)}&per_page=1"
        )
        if resp is None:
            return None
        try:
            body = json.loads(resp.read().decode("utf-8"))
            if body and isinstance(body, list) and len(body) > 0:
                return body[0].get("id")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        return None

    def create_repo(self, name: str, private: bool = True) -> Optional[str]:
        visibility = "private" if private else "public"
        resp = self._request("/projects", method="POST",
                             data={"name": name, "visibility": visibility})
        if resp is None:
            return None
        try:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("http_url_to_repo")
        except (json.JSONDecodeError, KeyError):
            return None

    def validate_token(self, token: str) -> Optional[str]:
        url = f"{self.api_base}/user"
        req = urllib.request.Request(url, headers={
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("username")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError):
            return None

    def get_https_url(self, owner: str, repo: str) -> str:
        return f"https://{self.host}/{owner}/{repo}.git"

    def add_collaborator(self, owner: str, repo: str, username: str) -> bool:
        # Look up user_id from username
        resp = self._request(f"/users?username={urllib.parse.quote(username)}")
        if resp is None:
            return False
        try:
            users = json.loads(resp.read().decode("utf-8"))
            if not users:
                return False
            user_id = users[0]["id"]
        except (json.JSONDecodeError, KeyError, IndexError):
            return False

        # Add as Developer (access_level=30)
        project_path = urllib.parse.quote(f"{owner}/{repo}", safe="")
        resp = self._request(
            f"/projects/{project_path}/members",
            method="POST",
            data={"user_id": user_id, "access_level": 30},
        )
        return resp is not None


class GenericGitProvider(GitProvider):
    """Fallback provider for non-GitHub/GitLab hosts"""

    def get_latest_sha(self, owner: str, repo: str, branch: str = None) -> Optional[str]:
        return None

    def create_repo(self, name: str, private: bool = True) -> Optional[str]:
        return None

    def validate_token(self, token: str) -> Optional[str]:
        return None

    def get_https_url(self, owner: str, repo: str) -> str:
        return ""

    def add_collaborator(self, owner: str, repo: str, username: str) -> bool:
        return False


def parse_remote_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse a git remote URL into (host, owner, repo).

    Handles HTTPS and SSH formats:
      - https://github.com/user/repo.git
      - git@github.com:user/repo.git
      - https://gitlab.com/user/repo
    """
    # SSH format: git@host:owner/repo.git
    ssh_match = re.match(r"^git@([^:]+):([^/]+)/(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2), ssh_match.group(3)

    # HTTPS format: https://host/owner/repo[.git]
    https_match = re.match(r"^https?://([^/]+)/([^/]+)/(.+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2), https_match.group(3)

    return None, None, None


def detect_provider(remote_url: str, config) -> GitProvider:
    """Detect the appropriate git provider from a remote URL.

    Uses config to retrieve tokens (github_token, gitlab_token) and
    optional gitlab_host for self-hosted GitLab detection.
    """
    host, _, _ = parse_remote_url(remote_url)

    if host == "github.com":
        token = config.get("github_token")
        if token:
            return GitHubProvider(token)

    gitlab_host = config.get("gitlab_host")
    if host == "gitlab.com" or (gitlab_host and host == gitlab_host):
        token = config.get("gitlab_token")
        if token:
            return GitLabProvider(token, host=host)

    return GenericGitProvider()
