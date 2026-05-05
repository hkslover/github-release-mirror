from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
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
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class Dependency:
    id: str
    name: str
    repo: str
    include_patterns: list[str]
    enabled: bool = True


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    dependencies: list[Dependency]
    enabled: bool = True


class SyncError(RuntimeError):
    """Raised when the sync operation cannot continue safely."""


def now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _validate_id(entity: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise SyncError(f"{entity} is required")
    if not ID_PATTERN.match(normalized):
        raise SyncError(
            f"Invalid {entity} '{normalized}', expected pattern {ID_PATTERN.pattern}"
        )
    return normalized


def _as_dict(value: Any, entity: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncError(f"{entity} must be an object")
    return value


def _as_list(value: Any, entity: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SyncError(f"{entity} must be a list")
    return value


def _validate_regex_patterns(patterns: list[str], context: str) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SyncError(f"Invalid include_patterns regex '{pattern}' in {context}: {exc}") from exc


def load_projects(path: str | Path) -> list[Project]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise SyncError(
            "PyYAML is required to parse mirror/projects.yaml. Install dependencies first."
        ) from exc

    content = Path(path).read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) or {}
    if not isinstance(parsed, dict):
        raise SyncError("projects.yaml root must be an object with a 'projects' field")
    raw_projects = _as_list(parsed.get("projects", []), "projects")

    seen_project_ids: set[str] = set()
    projects: list[Project] = []

    for raw_project in raw_projects:
        project_obj = _as_dict(raw_project, "project")
        project_id = _validate_id("project.id", str(project_obj.get("id", "")))
        project_name = str(project_obj.get("name", "")).strip()
        if not project_name:
            raise SyncError(f"project '{project_id}' is missing required field: name")
        if project_id in seen_project_ids:
            raise SyncError(f"Duplicate project.id '{project_id}'")
        seen_project_ids.add(project_id)

        dependencies: list[Dependency] = []
        seen_dependency_ids: set[str] = set()
        raw_dependencies = _as_list(
            project_obj.get("dependencies", []), f"project '{project_id}' dependencies"
        )
        for raw_dependency in raw_dependencies:
            dependency_obj = _as_dict(raw_dependency, f"dependency in project '{project_id}'")
            dependency_id = _validate_id(
                "dependency.id", str(dependency_obj.get("id", ""))
            )
            if dependency_id in seen_dependency_ids:
                raise SyncError(
                    f"Duplicate dependency.id '{dependency_id}' in project '{project_id}'"
                )
            seen_dependency_ids.add(dependency_id)

            dependency_name = str(dependency_obj.get("name", "")).strip()
            if not dependency_name:
                raise SyncError(
                    f"dependency '{dependency_id}' in project '{project_id}' is missing name"
                )

            repo = str(dependency_obj.get("repo", "")).strip()
            if not repo:
                raise SyncError(
                    f"dependency '{dependency_id}' in project '{project_id}' is missing repo"
                )
            if repo.count("/") != 1:
                raise SyncError(
                    f"Invalid repo format '{repo}', expected 'owner/name' in dependency '{dependency_id}'"
                )

            include_patterns = [str(v) for v in _as_list(
                dependency_obj.get("include_patterns", []),
                f"dependency '{dependency_id}' include_patterns",
            )]
            _validate_regex_patterns(
                include_patterns, f"dependency '{dependency_id}' in project '{project_id}'"
            )

            dependency_enabled = bool(dependency_obj.get("enabled", True))
            if dependency_enabled:
                dependencies.append(
                    Dependency(
                        id=dependency_id,
                        name=dependency_name,
                        repo=repo,
                        include_patterns=include_patterns,
                        enabled=True,
                    )
                )

        if bool(project_obj.get("enabled", True)):
            projects.append(
                Project(
                    id=project_id,
                    name=project_name,
                    dependencies=sorted(dependencies, key=lambda item: item.id),
                    enabled=True,
                )
            )

    return sorted(projects, key=lambda item: item.id)


def load_public_bundle(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    base = Path(path)
    if not base.exists():
        return {}
    index_path = base / "index.json"
    if not index_path.exists():
        return {}

    try:
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"Invalid index JSON: {index_path}") from exc

    projects: dict[str, dict[str, Any]] = {}
    raw_projects = index_payload.get("projects", {})
    if isinstance(raw_projects, dict):
        for project_id, project_meta in raw_projects.items():
            if not isinstance(project_meta, dict):
                continue
            manifest_file = str(project_meta.get("manifest", f"{project_id}.json")).strip()
            if not manifest_file:
                manifest_file = f"{project_id}.json"
            project_manifest_path = base / manifest_file
            if not project_manifest_path.exists():
                continue
            try:
                projects[str(project_id)] = json.loads(
                    project_manifest_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                raise SyncError(f"Invalid project manifest JSON: {project_manifest_path}") from exc

    return {
        "index": index_payload,
        "projects": projects,
    }


def github_get_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "release-r2-mirror/2.0",
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


def build_asset_key(project_id: str, repo: str, tag: str, asset_name: str) -> str:
    owner, repo_name = repo.split("/", 1)
    return "/".join(
        [
            urllib.parse.quote(project_id, safe=""),
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo_name, safe=""),
            urllib.parse.quote(tag, safe=""),
            urllib.parse.quote(asset_name, safe=""),
        ]
    )


def build_public_asset_url(base_download_url: str, key: str) -> str:
    return f"{base_download_url.rstrip('/')}/{key.lstrip('/')}"


def _asset_entry_from_github_asset(
    project_id: str,
    repo: str,
    tag: str,
    base_download_url: str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    name = str(asset.get("name", ""))
    if not name:
        raise SyncError(f"Asset without a name in {repo}@{tag}")
    key = build_asset_key(project_id=project_id, repo=repo, tag=tag, asset_name=name)
    return {
        "name": name,
        "size": int(asset.get("size", 0)),
        "key": key,
        "url": build_public_asset_url(base_download_url, key),
        "download_url": str(asset.get("browser_download_url", "")),
    }


def _latest_release_manifest_entry(
    project_id: str,
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
        _asset_entry_from_github_asset(project_id, repo, tag, base_download_url, asset)
        for asset in selected_assets
    ]

    return {
        "tag": tag,
        "published_at": release.get("published_at"),
        "assets": release_assets,
    }


def build_desired_internal_manifest(
    projects: list[Project],
    base_download_url: str,
    github_token: str | None,
) -> dict[str, Any]:
    project_payloads: dict[str, Any] = {}
    dependencies_count = 0

    for project in projects:
        dependency_payloads: dict[str, Any] = {}
        for dependency in project.dependencies:
            releases = get_repo_releases(dependency.repo, github_token)
            latest_release = select_latest_stable_release(releases)
            latest = _latest_release_manifest_entry(
                project_id=project.id,
                repo=dependency.repo,
                release=latest_release,
                include_patterns=dependency.include_patterns,
                base_download_url=base_download_url,
            )
            dependency_payloads[dependency.id] = {
                "id": dependency.id,
                "name": dependency.name,
                "repo": dependency.repo,
                "latest": latest,
            }
            dependencies_count += 1

        project_payloads[project.id] = {
            "id": project.id,
            "name": project.name,
            "dependencies": dependency_payloads,
        }

    return {
        "generated_at": now_iso8601(),
        "base_download_url": base_download_url.rstrip("/"),
        "projects": project_payloads,
        "projects_count": len(project_payloads),
        "dependencies_count": dependencies_count,
    }


def _to_public_latest_release(release: dict[str, Any] | None) -> dict[str, Any] | None:
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


def to_public_bundle(internal_manifest: dict[str, Any]) -> dict[str, Any]:
    generated_at = internal_manifest.get("generated_at")
    base_download_url = internal_manifest.get("base_download_url")
    index_projects: dict[str, Any] = {}
    project_manifests: dict[str, Any] = {}

    for project_id in sorted(internal_manifest.get("projects", {}).keys()):
        project = internal_manifest["projects"][project_id]
        manifest_filename = f"{project_id}.json"
        index_projects[project_id] = {
            "name": project.get("name"),
            "manifest": manifest_filename,
        }

        dependencies: dict[str, Any] = {}
        raw_dependencies = project.get("dependencies", {})
        for dependency_id in sorted(raw_dependencies.keys()):
            dependency = raw_dependencies[dependency_id]
            latest = _to_public_latest_release(dependency.get("latest"))
            dependencies[dependency_id] = {
                "name": dependency.get("name"),
                "repo": dependency.get("repo"),
                "latest_tag": latest.get("tag_name") if latest else None,
                "latest": latest,
            }

        project_manifests[project_id] = {
            "generated_at": generated_at,
            "base_download_url": base_download_url,
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
            },
            "dependencies": dependencies,
        }

    return {
        "index": {
            "generated_at": generated_at,
            "base_download_url": base_download_url,
            "projects": index_projects,
        },
        "projects": project_manifests,
    }


def _normalize_release(release: dict[str, Any] | None) -> dict[str, Any] | None:
    if not release:
        return None
    assets = sorted(
        release.get("assets", []),
        key=lambda item: (item.get("name", ""), item.get("size", 0), item.get("url", "")),
    )
    return {
        "tag": release.get("tag"),
        "tag_name": release.get("tag_name"),
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


def _normalize_project_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    dependencies: dict[str, Any] = {}
    raw_dependencies = manifest.get("dependencies", {})
    if isinstance(raw_dependencies, dict):
        for dependency_id in sorted(raw_dependencies.keys()):
            dependency = raw_dependencies[dependency_id]
            dependencies[dependency_id] = {
                "name": dependency.get("name"),
                "repo": dependency.get("repo"),
                "latest_tag": dependency.get("latest_tag"),
                "latest": _normalize_release(dependency.get("latest")),
            }

    project = manifest.get("project", {})
    return {
        "base_download_url": manifest.get("base_download_url"),
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
        },
        "dependencies": dependencies,
    }


def _normalize_public_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    index = bundle.get("index", {})
    normalized = {
        "base_download_url": index.get("base_download_url"),
        "projects": {},
    }

    index_projects = index.get("projects", {})
    project_manifests = bundle.get("projects", {})
    if not isinstance(index_projects, dict):
        return normalized

    for project_id in sorted(index_projects.keys()):
        metadata = index_projects[project_id]
        if not isinstance(metadata, dict):
            continue
        normalized["projects"][project_id] = {
            "name": metadata.get("name"),
            "manifest": metadata.get("manifest"),
            "manifest_body": _normalize_project_manifest(project_manifests.get(project_id, {})),
        }
    return normalized


def bundles_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _normalize_public_bundle(a) == _normalize_public_bundle(b)


def _changed_project_ids(existing: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    existing_projects = existing.get("projects", {})
    desired_projects = desired.get("projects", {})
    project_ids = set(existing_projects.keys()) | set(desired_projects.keys())
    changed: list[str] = []
    for project_id in sorted(project_ids):
        existing_manifest = _normalize_project_manifest(existing_projects.get(project_id, {}))
        desired_manifest = _normalize_project_manifest(desired_projects.get(project_id, {}))
        if existing_manifest != desired_manifest:
            changed.append(project_id)
    return changed


def _iter_internal_latest_assets(internal_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for project in internal_manifest.get("projects", {}).values():
        for dependency in project.get("dependencies", {}).values():
            latest = dependency.get("latest")
            if latest:
                assets.extend(latest.get("assets", []))
    return assets


def _iter_public_latest_assets(public_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for project_manifest in public_bundle.get("projects", {}).values():
        dependencies = project_manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            continue
        for dependency in dependencies.values():
            latest = dependency.get("latest")
            if latest:
                assets.extend(latest.get("assets", []))
    return assets


def collect_internal_manifest_asset_keys(internal_manifest: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for asset in _iter_internal_latest_assets(internal_manifest):
        key = str(asset.get("key", "")).strip()
        if key:
            keys.add(key)
    return keys


def collect_public_bundle_asset_keys(public_bundle: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for asset in _iter_public_latest_assets(public_bundle):
        key = str(asset.get("key", "")).strip()
        if key:
            keys.add(key)
            continue
        url = str(asset.get("url", "")).strip()
        if not url:
            continue
        path = urllib.parse.urlparse(url).path.lstrip("/")
        if path:
            keys.add(path)
    return keys


def _download_to_temp(download_url: str, github_token: str | None) -> str:
    headers = {"User-Agent": "release-r2-mirror/2.0"}
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


def _create_r2_client(endpoint: str, access_key: str, secret_key: str) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _upload_asset(client: Any, bucket: str, key: str, local_path: str) -> None:
    content_type, _ = mimetypes.guess_type(local_path)
    extra_args: dict[str, Any] = {"CacheControl": ASSET_CACHE_CONTROL}
    if content_type:
        extra_args["ContentType"] = content_type
    client.upload_file(local_path, bucket, key, ExtraArgs=extra_args)


def _delete_keys(client: Any, bucket: str, keys: set[str]) -> int:
    if not keys:
        return 0
    deleted = 0
    key_list = sorted(keys)
    for index in range(0, len(key_list), 1000):
        batch = key_list[index : index + 1000]
        payload = {"Objects": [{"Key": key} for key in batch], "Quiet": True}
        result = client.delete_objects(Bucket=bucket, Delete=payload)
        deleted += len(result.get("Deleted", []))
    return deleted


def sync_r2_assets(
    desired_internal_manifest: dict[str, Any],
    existing_public_bundle: dict[str, Any],
    github_token: str | None,
    r2_endpoint: str,
    r2_access_key_id: str,
    r2_secret_access_key: str,
    r2_bucket: str,
) -> dict[str, int]:
    existing_keys = collect_public_bundle_asset_keys(existing_public_bundle)
    desired_keys = collect_internal_manifest_asset_keys(desired_internal_manifest)
    to_upload: list[tuple[str, str]] = []

    for asset in _iter_internal_latest_assets(desired_internal_manifest):
        key = str(asset.get("key", "")).strip()
        if not key or key in existing_keys:
            continue
        download_url = str(asset.get("download_url", "")).strip()
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
    return {"uploaded": uploaded, "deleted": deleted}


def write_public_bundle(output_dir: str | Path, public_bundle: dict[str, Any]) -> list[str]:
    output = Path(output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    written_files: list[str] = []
    index_path = output / "index.json"
    write_json(index_path, public_bundle["index"])
    written_files.append(index_path.name)

    for project_id, payload in sorted(public_bundle.get("projects", {}).items()):
        project_path = output / f"{project_id}.json"
        write_json(project_path, payload)
        written_files.append(project_path.name)

    return written_files


def _resolve_pages_domain(pages_custom_domain: str | None, previous_cname_file: str | None) -> str | None:
    if pages_custom_domain and pages_custom_domain.strip():
        return pages_custom_domain.strip()
    if previous_cname_file:
        path = Path(previous_cname_file)
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def _read_cname(path: str | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    value = file_path.read_text(encoding="utf-8").strip()
    return value or None


def write_cname(output_dir: str | Path, domain: str | None) -> str | None:
    if not domain:
        return None
    path = Path(output_dir) / "CNAME"
    path.write_text(domain + "\n", encoding="utf-8")
    return str(path)


def run_sync(
    projects_path: str,
    output_dir: str,
    previous_dir: str | None,
    dry_run: bool,
    pages_custom_domain: str | None = None,
    previous_cname_file: str | None = None,
) -> dict[str, Any]:
    projects = load_projects(projects_path)

    base_download_url = os.getenv("R2_PUBLIC_BASE_URL", "").strip()
    if not base_download_url:
        raise SyncError("Missing required env var: R2_PUBLIC_BASE_URL")

    github_token = os.getenv("GH_RELEASE_TOKEN")
    existing_public_bundle = load_public_bundle(previous_dir)
    desired_internal_manifest = build_desired_internal_manifest(
        projects=projects,
        base_download_url=base_download_url,
        github_token=github_token,
    )
    desired_public_bundle = to_public_bundle(desired_internal_manifest)

    manifest_changed = not bundles_equivalent(existing_public_bundle, desired_public_bundle)
    changed_projects = _changed_project_ids(existing_public_bundle, desired_public_bundle)
    pages_domain = _resolve_pages_domain(pages_custom_domain, previous_cname_file)
    existing_domain = _read_cname(previous_cname_file)
    cname_changed = pages_domain != existing_domain
    changed = manifest_changed or cname_changed
    upload_stats = {"uploaded": 0, "deleted": 0}

    if manifest_changed and not dry_run:
        required_vars = ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
        missing = [name for name in required_vars if not os.getenv(name, "").strip()]
        if missing:
            raise SyncError(f"Missing required R2 env vars: {', '.join(missing)}")

        upload_stats = sync_r2_assets(
            desired_internal_manifest=desired_internal_manifest,
            existing_public_bundle=existing_public_bundle,
            github_token=github_token,
            r2_endpoint=os.environ["R2_ENDPOINT"],
            r2_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            r2_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            r2_bucket=os.environ["R2_BUCKET"],
        )

    written_files = write_public_bundle(output_dir=output_dir, public_bundle=desired_public_bundle)
    cname_path = write_cname(output_dir=output_dir, domain=pages_domain)
    if cname_path:
        written_files.append("CNAME")

    return {
        "changed": changed,
        "manifest_changed": manifest_changed,
        "cname_changed": cname_changed,
        "projects_count": desired_internal_manifest["projects_count"],
        "dependencies_count": desired_internal_manifest["dependencies_count"],
        "changed_projects": changed_projects,
        "uploaded": upload_stats["uploaded"],
        "deleted": upload_stats["deleted"],
        "output_dir": str(output_dir),
        "written_files": sorted(written_files),
        "manifest_cache_control": MANIFEST_CACHE_CONTROL,
        "asset_cache_control": ASSET_CACHE_CONTROL,
        "generated_at": desired_internal_manifest["generated_at"],
    }
