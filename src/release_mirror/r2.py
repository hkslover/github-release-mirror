from __future__ import annotations

import mimetypes
import os
import tempfile
import urllib.request
from typing import Any

from .errors import SyncError
from .manifest import (
    collect_internal_manifest_asset_keys,
    collect_public_bundle_asset_keys,
    iter_internal_latest_assets,
)

ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _download_to_temp(download_url: str, github_token: str | None) -> str:
    headers = {"User-Agent": "release-r2-mirror/2.1"}
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

    for asset in iter_internal_latest_assets(desired_internal_manifest):
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
