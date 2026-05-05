from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
MANIFEST_CACHE_CONTROL = "public, max-age=60"


@dataclass(frozen=True)
class Dependency:
    repo: str
    include_patterns: list[str]
    enabled: bool = True


class SyncError(RuntimeError):
    """Raised when the sync operation cannot continue safely."""


def now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_dependencies(path: str | Path) -> list[Dependency]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise SyncError(
            "PyYAML is required to parse mirror/deps.yaml. Install dependencies first."
        ) from exc

    content = Path(path).read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) or {}

    if isinstance(parsed, list):
        raw_dependencies = parsed
    else:
        raw_dependencies = parsed.get("dependencies", [])

    dependencies: list[Dependency] = []
    for item in raw_dependencies:
        repo = str(item.get("repo", "")).strip()
        if not repo:
            raise SyncError("Dependency entry is missing required field: repo")
        if repo.count("/") != 1:
            raise SyncError(f"Invalid repo format '{repo}', expected 'owner/name'")
        include_patterns = item.get("include_patterns", []) or []
        dependencies.append(
            Dependency(
                repo=repo,
                include_patterns=[str(pattern) for pattern in include_patterns],
                enabled=bool(item.get("enabled", True)),
            )
        )
    return [dep for dep in dependencies if dep.enabled]


def load_manifest(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"Invalid manifest JSON: {manifest_path}") from exc


def github_get_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "release-r2-mirror/1.0",
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


def select_latest_and_previous(
    releases: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    stable = [
        release
        for release in releases
        if release.get("tag_name")
        and not bool(release.get("draft", False))
        and not bool(release.get("prerelease", False))
    ]
    if not stable:
        return None, None
    latest = stable[0]
    previous = stable[1] if len(stable) > 1 else None
    return latest, previous


def filter_assets(assets: list[dict[str, Any]], include_patterns: list[str]) -> list[dict[str, Any]]:
    if not include_patterns:
        return assets
    patterns = []
    for pattern in include_patterns:
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise SyncError(f"Invalid include_patterns regex '{pattern}': {exc}") from exc

    filtered: list[dict[str, Any]] = []
    for asset in assets:
        name = str(asset.get("name", ""))
        if any(pattern.search(name) for pattern in patterns):
            filtered.append(asset)
    return filtered


def build_asset_key(repo: str, tag: str, asset_name: str) -> str:
    return "/".join(
        [
            urllib.parse.quote(repo.split("/")[0], safe=""),
            urllib.parse.quote(repo.split("/")[1], safe=""),
            urllib.parse.quote(tag, safe=""),
            urllib.parse.quote(asset_name, safe=""),
        ]
    )


def build_public_asset_url(base_download_url: str, key: str) -> str:
    return f"{base_download_url.rstrip('/')}/{key.lstrip('/')}"


def _normalize_manifest_for_compare(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "base_download_url": manifest.get("base_download_url", ""),
        "projects": [],
    }
    for project in sorted(manifest.get("projects", []), key=lambda item: item.get("repo", "")):
        project_copy = {
            "repo": project.get("repo"),
            "latest": _normalize_release(project.get("latest")),
            "previous": _normalize_release(project.get("previous")),
        }
        normalized["projects"].append(project_copy)
    return normalized


def _normalize_release(release: dict[str, Any] | None) -> dict[str, Any] | None:
    if not release:
        return None
    assets = sorted(
        release.get("assets", []),
        key=lambda item: (item.get("name", ""), item.get("size", 0), item.get("url", "")),
    )
    return {
        "tag": release.get("tag"),
        "published_at": release.get("published_at"),
        "assets": [
            {
                "name": asset.get("name"),
                "size": asset.get("size"),
                "url": asset.get("url"),
            }
            for asset in assets
        ],
    }


def manifests_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _normalize_manifest_for_compare(a) == _normalize_manifest_for_compare(b)


def _asset_entry_from_github_asset(
    repo: str,
    tag: str,
    base_download_url: str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    name = str(asset.get("name", ""))
    if not name:
        raise SyncError(f"Asset without a name in {repo}@{tag}")

    key = build_asset_key(repo, tag, name)
    return {
        "name": name,
        "size": int(asset.get("size", 0)),
        "key": key,
        "url": build_public_asset_url(base_download_url, key),
        "download_url": asset.get("browser_download_url", ""),
    }


def _release_manifest_entry(
    repo: str,
    release: dict[str, Any] | None,
    include_patterns: list[str],
    base_download_url: str,
) -> dict[str, Any] | None:
    if not release:
        return None

    tag = str(release.get("tag_name", "")).strip()
    if not tag:
        return None

    assets = release.get("assets", []) or []
    selected_assets = filter_assets(list(assets), include_patterns)

    release_assets = [
        _asset_entry_from_github_asset(repo, tag, base_download_url, asset)
        for asset in selected_assets
    ]

    return {
        "tag": tag,
        "published_at": release.get("published_at"),
        "assets": release_assets,
    }


def build_desired_manifest(
    dependencies: list[Dependency],
    base_download_url: str,
    github_token: str | None,
) -> dict[str, Any]:
    projects: list[dict[str, Any]] = []

    for dependency in dependencies:
        releases = get_repo_releases(dependency.repo, github_token)
        latest, previous = select_latest_and_previous(releases)
        latest_entry = _release_manifest_entry(
            dependency.repo,
            latest,
            dependency.include_patterns,
            base_download_url,
        )
        previous_entry = _release_manifest_entry(
            dependency.repo,
            previous,
            dependency.include_patterns,
            base_download_url,
        )

        projects.append(
            {
                "repo": dependency.repo,
                "latest": latest_entry,
                "previous": previous_entry,
            }
        )

    projects.sort(key=lambda item: item["repo"])
    return {
        "generated_at": now_iso8601(),
        "base_download_url": base_download_url.rstrip("/"),
        "projects": projects,
    }


def to_public_manifest(internal_manifest: dict[str, Any]) -> dict[str, Any]:
    public_projects: list[dict[str, Any]] = []
    for project in internal_manifest.get("projects", []):
        latest = _to_public_release(project.get("latest"))
        previous = _to_public_release(project.get("previous"))
        public_projects.append(
            {
                "repo": project.get("repo"),
                # Keep top-level tags for easier client-side version checks.
                "latest_tag": latest.get("tag_name") if latest else None,
                "previous_tag": previous.get("tag_name") if previous else None,
                "latest": latest,
                "previous": previous,
            }
        )
    return {
        "generated_at": internal_manifest.get("generated_at"),
        "base_download_url": internal_manifest.get("base_download_url"),
        "projects": public_projects,
    }


def _to_public_release(release: dict[str, Any] | None) -> dict[str, Any] | None:
    if not release:
        return None

    tag = release.get("tag")
    return {
        "tag": tag,
        "tag_name": tag,
        "published_at": release.get("published_at"),
        "assets": [
            {
                "name": asset.get("name"),
                "size": asset.get("size"),
                "url": asset.get("url"),
            }
            for asset in release.get("assets", [])
        ],
    }


def _iter_release_assets(project: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for slot in ("latest", "previous"):
        release = project.get(slot)
        if not release:
            continue
        assets.extend(release.get("assets", []))
    return assets


def collect_manifest_asset_keys(manifest: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for project in manifest.get("projects", []):
        for asset in _iter_release_assets(project):
            key = str(asset.get("key", "")).strip()
            if key:
                keys.add(key)
                continue
            url = str(asset.get("url", "")).strip()
            if url:
                path = urllib.parse.urlparse(url).path.lstrip("/")
                if path:
                    keys.add(path)
    return keys


def _download_to_temp(download_url: str, github_token: str | None) -> str:
    headers = {"User-Agent": "release-r2-mirror/1.0"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = urllib.request.Request(url=download_url, method="GET", headers=headers)

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    try:
        with urllib.request.urlopen(request, timeout=120) as response, open(temp_path, "wb") as file_obj:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_obj.write(chunk)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    return temp_path


def _create_r2_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _upload_asset(
    client: Any,
    bucket: str,
    key: str,
    local_path: str,
) -> None:
    content_type, _ = mimetypes.guess_type(local_path)
    extra_args = {
        "CacheControl": ASSET_CACHE_CONTROL,
    }
    if content_type:
        extra_args["ContentType"] = content_type

    client.upload_file(local_path, bucket, key, ExtraArgs=extra_args)


def _delete_keys(client: Any, bucket: str, keys: set[str]) -> int:
    if not keys:
        return 0

    key_list = sorted(keys)
    deleted = 0
    for index in range(0, len(key_list), 1000):
        batch = key_list[index : index + 1000]
        payload = {"Objects": [{"Key": key} for key in batch], "Quiet": True}
        result = client.delete_objects(Bucket=bucket, Delete=payload)
        deleted += len(result.get("Deleted", []))
    return deleted


def sync_r2_assets(
    desired_manifest: dict[str, Any],
    existing_manifest: dict[str, Any],
    github_token: str | None,
    r2_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_bucket: str,
) -> dict[str, int]:
    existing_keys = collect_manifest_asset_keys(existing_manifest)
    desired_keys = collect_manifest_asset_keys(desired_manifest)
    to_upload: list[tuple[str, str]] = []

    for project in desired_manifest.get("projects", []):
        for asset in _iter_release_assets(project):
            key = str(asset.get("key", ""))
            if not key or key in existing_keys:
                continue
            download_url = str(asset.get("download_url", ""))
            if not download_url:
                raise SyncError(f"Asset {asset.get('name')} has empty download_url")
            to_upload.append((key, download_url))

    client = _create_r2_client(
        endpoint=r2_endpoint,
        access_key=r2_access_key_id,
        secret_key=r2_secret_access_key,
    )

    uploaded = 0
    for key, download_url in to_upload:
        local_path = _download_to_temp(download_url, github_token)
        try:
            _upload_asset(client=client, bucket=r2_bucket, key=key, local_path=local_path)
            uploaded += 1
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    stale_keys = existing_keys - desired_keys
    deleted = _delete_keys(client=client, bucket=r2_bucket, keys=stale_keys)

    return {
        "uploaded": uploaded,
        "deleted": deleted,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_sync(
    deps_path: str,
    output_manifest_path: str,
    previous_manifest_path: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    dependencies = load_dependencies(deps_path)

    base_download_url = os.getenv("R2_PUBLIC_BASE_URL", "").strip()
    if not base_download_url:
        raise SyncError("Missing required env var: R2_PUBLIC_BASE_URL")

    github_token = os.getenv("GH_RELEASE_TOKEN")
    existing_manifest = load_manifest(previous_manifest_path)
    desired_internal_manifest = build_desired_manifest(
        dependencies=dependencies,
        base_download_url=base_download_url,
        github_token=github_token,
    )
    desired_manifest = to_public_manifest(desired_internal_manifest)

    changed = not manifests_equivalent(existing_manifest, desired_manifest)
    upload_stats = {"uploaded": 0, "deleted": 0}

    if changed and not dry_run:
        required_vars = [
            "R2_ENDPOINT",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        ]
        missing = [name for name in required_vars if not os.getenv(name, "").strip()]
        if missing:
            raise SyncError(f"Missing required R2 env vars: {', '.join(missing)}")

        upload_stats = sync_r2_assets(
            desired_manifest=desired_internal_manifest,
            existing_manifest=existing_manifest,
            github_token=github_token,
            r2_endpoint=os.environ["R2_ENDPOINT"],
            r2_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            r2_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            r2_bucket=os.environ["R2_BUCKET"],
        )

    write_json(output_manifest_path, desired_manifest)

    return {
        "changed": changed,
        "projects": len(desired_manifest.get("projects", [])),
        "uploaded": upload_stats["uploaded"],
        "deleted": upload_stats["deleted"],
        "manifest_path": str(output_manifest_path),
        "manifest_cache_control": MANIFEST_CACHE_CONTROL,
        "asset_cache_control": ASSET_CACHE_CONTROL,
        "generated_at": desired_manifest["generated_at"],
    }
