from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Project
from .errors import SyncError
from .github_api import filter_assets, get_repo_releases, select_latest_stable_release

GH_PROXY_PREFIX = "https://gh-proxy.org/"


def now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def build_mirror_url(github_url: str | None) -> str | None:
    if not github_url:
        return None
    value = github_url.strip()
    if not value:
        return None
    return f"{GH_PROXY_PREFIX}{value}"


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
    download_url = str(asset.get("browser_download_url", "")).strip()
    return {
        "name": name,
        "size": int(asset.get("size", 0)),
        "key": key,
        "url": build_public_asset_url(base_download_url, key),
        "download_url": download_url,
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

        project_payload = {
            "id": project.id,
            "name": project.name,
            "dependencies": dependency_payloads,
        }
        if project.ads is not None:
            project_payload["ads"] = {
                "version": project.ads.version,
                "items": [
                    {
                        "id": item.id,
                        "enabled": item.enabled,
                        "placement": item.placement,
                        "click_url": item.click_url,
                        "sponsor": item.sponsor,
                        "title": item.title,
                        "rich_html": item.rich_html,
                        "image_url": item.image_url,
                        "image_alt": item.image_alt,
                    }
                    for item in project.ads.items
                ],
            }
        project_payloads[project.id] = project_payload

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
                "github_url": asset.get("download_url") or None,
                "mirror_url": build_mirror_url(asset.get("download_url")),
            }
            for asset in release.get("assets", [])
        ],
    }


def _normalize_ads_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("id"),
        "enabled": bool(item.get("enabled", True)),
        "placement": item.get("placement"),
        "click_url": item.get("click_url"),
        "sponsor": item.get("sponsor"),
        "title": item.get("title"),
        "rich_html": item.get("rich_html"),
        "image_url": item.get("image_url"),
        "image_alt": item.get("image_alt"),
    }


def _canonical_ads_payload(ads: Any) -> dict[str, Any] | None:
    if not isinstance(ads, dict):
        return None
    items: list[dict[str, Any]] = []
    raw_items = ads.get("items", [])
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            normalized_item = _normalize_ads_item(raw_item)
            if normalized_item is not None:
                items.append(normalized_item)
    return {
        "version": ads.get("version"),
        "items": items,
    }


def _resolve_public_ads(
    project_id: str,
    generated_at: Any,
    internal_ads: Any,
    previous_public_bundle: dict[str, Any] | None,
) -> dict[str, Any] | None:
    desired_ads = _canonical_ads_payload(internal_ads)
    if desired_ads is None:
        return None

    previous_ads: dict[str, Any] | None = None
    if isinstance(previous_public_bundle, dict):
        previous_projects = previous_public_bundle.get("projects", {})
        if isinstance(previous_projects, dict):
            previous_project = previous_projects.get(project_id)
            if isinstance(previous_project, dict):
                raw_previous_ads = previous_project.get("ads")
                if isinstance(raw_previous_ads, dict):
                    previous_ads = raw_previous_ads

    previous_updated_at = None
    if isinstance(previous_ads, dict):
        raw_updated_at = previous_ads.get("updated_at")
        if isinstance(raw_updated_at, str) and raw_updated_at.strip():
            previous_updated_at = raw_updated_at.strip()

    unchanged_ads = desired_ads == _canonical_ads_payload(previous_ads)
    updated_at = (
        previous_updated_at
        if unchanged_ads and previous_updated_at
        else str(generated_at or "").strip()
    )
    return {
        "version": desired_ads.get("version"),
        "updated_at": updated_at,
        "items": desired_ads.get("items", []),
    }


def to_public_bundle(
    internal_manifest: dict[str, Any],
    previous_public_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

        project_manifest = {
            "generated_at": generated_at,
            "base_download_url": base_download_url,
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
            },
            "dependencies": dependencies,
        }
        ads = _resolve_public_ads(
            project_id=project_id,
            generated_at=generated_at,
            internal_ads=project.get("ads"),
            previous_public_bundle=previous_public_bundle,
        )
        if ads is not None:
            project_manifest["ads"] = ads
        project_manifests[project_id] = project_manifest

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
        key=lambda item: (
            item.get("name", ""),
            item.get("size", 0),
            item.get("url", ""),
            item.get("github_url", ""),
            item.get("mirror_url", ""),
        ),
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
                "github_url": asset.get("github_url"),
                "mirror_url": asset.get("mirror_url"),
            }
            for asset in assets
        ],
    }


def _normalize_ads_for_comparison(ads: Any) -> dict[str, Any] | None:
    if not isinstance(ads, dict):
        return None
    normalized = _canonical_ads_payload(ads)
    if normalized is None:
        return None
    return {
        "version": normalized.get("version"),
        "updated_at": ads.get("updated_at"),
        "items": normalized.get("items", []),
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
        "ads": _normalize_ads_for_comparison(manifest.get("ads")),
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


def changed_project_ids(existing: dict[str, Any], desired: dict[str, Any]) -> list[str]:
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


def iter_internal_latest_assets(internal_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for project in internal_manifest.get("projects", {}).values():
        for dependency in project.get("dependencies", {}).values():
            latest = dependency.get("latest")
            if latest:
                assets.extend(latest.get("assets", []))
    return assets


def iter_public_latest_assets(public_bundle: dict[str, Any]) -> list[dict[str, Any]]:
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
    for asset in iter_internal_latest_assets(internal_manifest):
        key = str(asset.get("key", "")).strip()
        if key:
            keys.add(key)
    return keys


def collect_public_bundle_asset_keys(public_bundle: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for asset in iter_public_latest_assets(public_bundle):
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
