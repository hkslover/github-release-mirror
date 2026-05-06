from __future__ import annotations

import re
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
class Project:
    id: str
    name: str
    dependencies: list[Dependency]
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
                    enabled=True,
                )
            )

    return sorted(projects, key=lambda item: item.id)
