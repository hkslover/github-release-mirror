import tempfile
import unittest
from pathlib import Path

from release_mirror.config import load_projects
from release_mirror.errors import SyncError


class ConfigValidationTest(unittest.TestCase):
    def test_load_projects_parses_enabled_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    enabled: true
    dependencies:
      - id: enabled-dep
        name: Enabled dep
        repo: owner/repo
        enabled: true
        include_patterns:
          - "\\\\.zip$"
      - id: disabled-dep
        name: Disabled dep
        repo: owner/repo2
        enabled: false
""".strip()
                + "\n",
                encoding="utf-8",
            )
            projects = load_projects(config)
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].id, "demo")
            self.assertEqual([dep.id for dep in projects[0].dependencies], ["enabled-dep"])

    def test_duplicate_project_id_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
  - id: demo
    name: Demo2
    dependencies: []
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(SyncError):
                load_projects(config)

    def test_duplicate_dependency_id_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies:
      - id: tool
        name: Tool A
        repo: owner/repo
      - id: tool
        name: Tool B
        repo: owner/repo2
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(SyncError):
                load_projects(config)

    def test_invalid_repo_format_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies:
      - id: tool
        name: Tool
        repo: invalid-repo
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(SyncError):
                load_projects(config)

    def test_invalid_include_pattern_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies:
      - id: tool
        name: Tool
        repo: owner/repo
        include_patterns:
          - "("
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(SyncError):
                load_projects(config)


if __name__ == "__main__":
    unittest.main()
