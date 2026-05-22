from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SyncError

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class Dependency:
    id: str
    name: str
    repo: str
    include_patterns: list[str]
    enabled: bool = True


@dataclass(frozen=True)
class AdItem:
    id: str
    placement: str
    click_url: str
    sponsor: str
    title: str
    rich_html: str
    image_url: str
    image_alt: str
    enabled: bool = True


@dataclass(frozen=True)
class AdsConfig:
    version: str
    items: list[AdItem]


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    dependencies: list[Dependency]
    ads: AdsConfig | None = None
    enabled: bool = True


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


def _require_non_empty_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"{context} is missing required field: {field}")
    return value.strip()


def _require_required_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"{context} is missing required field: {field}")
    return value


def _validate_http_url(value: str, field: str, context: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SyncError(
            f"Invalid {field} '{value}' in {context}, expected http/https URL"
        )
    return value


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

        ads: AdsConfig | None = None
        raw_ads = project_obj.get("ads")
        if raw_ads is not None:
            ads_obj = _as_dict(raw_ads, f"ads in project '{project_id}'")
            ads_version = _require_non_empty_string(
                ads_obj.get("version"),
                "version",
                f"ads in project '{project_id}'",
            )
            raw_ads_items = _as_list(
                ads_obj.get("items", []), f"ads.items in project '{project_id}'"
            )
            ads_items: list[AdItem] = []
            seen_ad_ids: set[str] = set()
            for raw_ad_item in raw_ads_items:
                ad_item_obj = _as_dict(
                    raw_ad_item, f"ads item in project '{project_id}'"
                )
                ad_id = _validate_id("ads.item.id", str(ad_item_obj.get("id", "")))
                if ad_id in seen_ad_ids:
                    raise SyncError(
                        f"Duplicate ads.item.id '{ad_id}' in project '{project_id}'"
                    )
                seen_ad_ids.add(ad_id)

                ad_context = f"ads item '{ad_id}' in project '{project_id}'"
                placement = _require_non_empty_string(
                    ad_item_obj.get("placement"), "placement", ad_context
                )
                click_url = _validate_http_url(
                    _require_non_empty_string(
                        ad_item_obj.get("click_url"), "click_url", ad_context
                    ),
                    "click_url",
                    ad_context,
                )
                sponsor = _require_non_empty_string(
                    ad_item_obj.get("sponsor"), "sponsor", ad_context
                )
                title = _require_non_empty_string(
                    ad_item_obj.get("title"), "title", ad_context
                )
                rich_html = _require_required_string(
                    ad_item_obj.get("rich_html"), "rich_html", ad_context
                )
                image_url = _validate_http_url(
                    _require_non_empty_string(
                        ad_item_obj.get("image_url"), "image_url", ad_context
                    ),
                    "image_url",
                    ad_context,
                )
                image_alt = _require_non_empty_string(
                    ad_item_obj.get("image_alt"), "image_alt", ad_context
                )

                if bool(ad_item_obj.get("enabled", True)):
                    ads_items.append(
                        AdItem(
                            id=ad_id,
                            placement=placement,
                            click_url=click_url,
                            sponsor=sponsor,
                            title=title,
                            rich_html=rich_html,
                            image_url=image_url,
                            image_alt=image_alt,
                            enabled=True,
                        )
                    )

            ads = AdsConfig(version=ads_version, items=ads_items)

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

            if bool(dependency_obj.get("enabled", True)):
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
                    ads=ads,
                    enabled=True,
                )
            )

    return sorted(projects, key=lambda item: item.id)
