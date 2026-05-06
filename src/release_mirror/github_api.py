from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .errors import SyncError


def github_get_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "release-r2-mirror/2.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url=url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SyncError(f"GitHub API request failed ({exc.code}) {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"GitHub API network error for {url}: {exc}") from exc


def get_repo_releases(repo: str, token: str | None) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
    payload = github_get_json(url, token)
    if not isinstance(payload, list):
        raise SyncError(f"Unexpected GitHub API response for {repo}")
    return payload


def select_latest_stable_release(releases: list[dict[str, Any]]) -> dict[str, Any] | None:
    for release in releases:
        if (
            release.get("tag_name")
            and not bool(release.get("draft", False))
            and not bool(release.get("prerelease", False))
        ):
            return release
    return None


def filter_assets(assets: list[dict[str, Any]], include_patterns: list[str]) -> list[dict[str, Any]]:
    if not include_patterns:
        return assets
    patterns = [re.compile(pattern) for pattern in include_patterns]
    filtered: list[dict[str, Any]] = []
    for asset in assets:
        name = str(asset.get("name", ""))
        if any(pattern.search(name) for pattern in patterns):
            filtered.append(asset)
    return filtered
