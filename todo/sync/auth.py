"""Layered auth resolution for git remotes (GitHub / GitLab)"""

import os
import subprocess
from typing import Optional
from urllib.parse import urlparse


_token_cache: dict = {}

_ENV_VARS = {
    "github": "TODO_GITHUB_TOKEN",
    "gitlab": "TODO_GITLAB_TOKEN",
}

_CLI_COMMANDS = {
    "github": ["gh", "auth", "token"],
    "gitlab": ["glab", "auth", "status", "-t"],
}

_CONFIG_KEYS = {
    "github": "github_token",
    "gitlab": "gitlab_token",
}

_CREDENTIAL_HOSTS = {
    "github": "github.com",
    "gitlab": "gitlab.com",
}


def resolve_token(provider: str, config, interactive: bool = True) -> Optional[str]:
    """Try multiple sources to resolve an auth token for the given provider.

    Sources are tried in order:
      1. Environment variable (TODO_GITHUB_TOKEN / TODO_GITLAB_TOKEN)
      2. CLI tool (gh / glab)
      3. Config file
      4. Git credential helper (skipped when interactive=False)
      5. Returns None if nothing found
    """
    if provider in _token_cache:
        return _token_cache[provider]

    token = (
        _token_from_env(provider)
        or _token_from_cli(provider)
        or _token_from_config(provider, config)
        or (_token_from_git_credential(provider) if interactive else None)
    )

    if token:
        _token_cache[provider] = token

    return token


def clear_token_cache():
    """Reset the per-process token cache."""
    _token_cache.clear()


def get_git_auth_env(token: str, remote_url: str) -> dict:
    """Return env vars for transient HTTPS credential injection.

    For SSH URLs only GIT_TERMINAL_PROMPT=0 is returned.
    For HTTPS URLs a one-shot credential helper is configured via
    the GIT_CONFIG_COUNT / GIT_CONFIG_KEY / GIT_CONFIG_VALUE pattern.
    """
    env = {"GIT_TERMINAL_PROMPT": "0"}

    if not is_https_url(remote_url):
        return env

    helper = f"!f() {{ echo username=x-access-token; echo password={token}; }}; f"
    env.update({
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": helper,
    })
    return env


def is_https_url(url: str) -> bool:
    """Return True if *url* looks like an HTTPS remote."""
    return url.startswith("https://") or url.startswith("http://")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _token_from_env(provider):
    var = _ENV_VARS.get(provider)
    if var:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return None


def _token_from_cli(provider):
    cmd = _CLI_COMMANDS.get(provider)
    if not cmd:
        return None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
        )
        if result.returncode == 0:
            # gh prints the token on stdout; glab buries it in stderr
            output = result.stdout.strip() or result.stderr.strip()
            # glab prints lines like "Token: gho_xxxx", extract the value
            if provider == "gitlab":
                for line in output.splitlines():
                    if line.strip().lower().startswith("token:"):
                        return line.split(":", 1)[1].strip()
            if output:
                return output
    except FileNotFoundError:
        pass
    return None


def _token_from_config(provider, config):
    key = _CONFIG_KEYS.get(provider)
    if key:
        val = config.get(key)
        if val:
            return val
    return None


def _token_from_git_credential(provider):
    host = _CREDENTIAL_HOSTS.get(provider)
    if not host:
        return None
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={host}\n\n",
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return None
