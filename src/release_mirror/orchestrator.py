from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import load_projects
from .errors import SyncError
from .manifest import (
    build_desired_internal_manifest,
    bundles_equivalent,
    changed_project_ids,
    load_public_bundle,
    to_public_bundle,
)
from .r2 import ASSET_CACHE_CONTROL, sync_r2_assets

MANIFEST_CACHE_CONTROL = "public, max-age=60"


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    changed_projects = changed_project_ids(existing_public_bundle, desired_public_bundle)
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
