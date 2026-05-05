import tempfile
import unittest
from pathlib import Path

from release_mirror.sync import (
    SyncError,
    build_asset_key,
    build_public_asset_url,
    bundles_equivalent,
    filter_assets,
    load_projects,
    select_latest_stable_release,
    to_public_bundle,
)


class SelectReleasesTest(unittest.TestCase):
    def test_selects_latest_stable_release(self) -> None:
        releases = [
            {"tag_name": "v3.0.0-rc1", "draft": False, "prerelease": True},
            {"tag_name": "v2.1.0", "draft": False, "prerelease": False},
            {"tag_name": "v2.0.0", "draft": False, "prerelease": False},
        ]
        latest = select_latest_stable_release(releases)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["tag_name"], "v2.1.0")

    def test_returns_none_when_no_stable_release(self) -> None:
        releases = [
            {"tag_name": "v1.0.0-rc1", "draft": False, "prerelease": True},
            {"tag_name": "v1.0.0", "draft": True, "prerelease": False},
        ]
        self.assertIsNone(select_latest_stable_release(releases))


class FilterAssetsTest(unittest.TestCase):
    def test_filters_assets_by_regex_patterns(self) -> None:
        assets = [
            {"name": "tool-linux-amd64.tar.gz", "size": 100},
            {"name": "tool-darwin-arm64.tar.gz", "size": 200},
            {"name": "checksum.txt", "size": 50},
        ]
        filtered = filter_assets(assets, [r"linux-amd64", r"darwin-arm64"])
        self.assertEqual(
            [asset["name"] for asset in filtered],
            ["tool-linux-amd64.tar.gz", "tool-darwin-arm64.tar.gz"],
        )


class UrlAndKeyTest(unittest.TestCase):
    def test_build_asset_key_uses_project_scoped_path(self) -> None:
        key = build_asset_key(
            project_id="demo-project",
            repo="owner/repo",
            tag="v1.2.3",
            asset_name="tool linux amd64.tar.gz",
        )
        self.assertEqual(
            key,
            "demo-project/owner/repo/v1.2.3/tool%20linux%20amd64.tar.gz",
        )

    def test_build_public_asset_url_strips_double_slash(self) -> None:
        url = build_public_asset_url(
            "https://downloads.example.com/",
            "demo-project/owner/repo/v1.2.3/a.zip",
        )
        self.assertEqual(
            url,
            "https://downloads.example.com/demo-project/owner/repo/v1.2.3/a.zip",
        )


class BundleComparisonTest(unittest.TestCase):
    def test_bundles_equivalent_ignores_generated_at(self) -> None:
        a = {
            "index": {
                "generated_at": "2026-05-05T00:00:00Z",
                "base_download_url": "https://downloads.example.com",
                "projects": {
                    "demo": {"name": "Demo", "manifest": "demo.json"},
                },
            },
            "projects": {
                "demo": {
                    "generated_at": "2026-05-05T00:00:00Z",
                    "base_download_url": "https://downloads.example.com",
                    "project": {"id": "demo", "name": "Demo"},
                    "dependencies": {
                        "tool": {
                            "name": "Tool",
                            "repo": "owner/repo",
                            "latest_tag": "v1.0.0",
                            "latest": {
                                "tag": "v1.0.0",
                                "tag_name": "v1.0.0",
                                "published_at": "2026-05-05T00:00:00Z",
                                "assets": [
                                    {
                                        "name": "a.zip",
                                        "size": 1,
                                        "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
                                    }
                                ],
                            },
                        }
                    },
                }
            },
        }
        b = {
            "index": {
                "generated_at": "2026-05-06T00:00:00Z",
                "base_download_url": "https://downloads.example.com",
                "projects": {
                    "demo": {"name": "Demo", "manifest": "demo.json"},
                },
            },
            "projects": {
                "demo": {
                    "generated_at": "2026-05-06T00:00:00Z",
                    "base_download_url": "https://downloads.example.com",
                    "project": {"id": "demo", "name": "Demo"},
                    "dependencies": {
                        "tool": {
                            "name": "Tool",
                            "repo": "owner/repo",
                            "latest_tag": "v1.0.0",
                            "latest": {
                                "tag": "v1.0.0",
                                "tag_name": "v1.0.0",
                                "published_at": "2026-05-05T00:00:00Z",
                                "assets": [
                                    {
                                        "name": "a.zip",
                                        "size": 1,
                                        "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
                                    }
                                ],
                            },
                        }
                    },
                }
            },
        }
        self.assertTrue(bundles_equivalent(a, b))

    def test_to_public_bundle_strips_internal_asset_fields(self) -> None:
        internal = {
            "generated_at": "2026-05-05T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": {
                "demo": {
                    "id": "demo",
                    "name": "Demo",
                    "dependencies": {
                        "tool": {
                            "id": "tool",
                            "name": "Tool",
                            "repo": "owner/repo",
                            "latest": {
                                "tag": "v1.0.0",
                                "published_at": "2026-05-05T00:00:00Z",
                                "assets": [
                                    {
                                        "name": "a.zip",
                                        "size": 1,
                                        "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
                                        "key": "demo/owner/repo/v1.0.0/a.zip",
                                        "download_url": "https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
                                    }
                                ],
                            },
                        }
                    },
                }
            },
        }
        public = to_public_bundle(internal)
        self.assertEqual(public["index"]["projects"]["demo"]["manifest"], "demo.json")
        dep = public["projects"]["demo"]["dependencies"]["tool"]
        self.assertEqual(dep["latest_tag"], "v1.0.0")
        self.assertEqual(dep["latest"]["tag"], "v1.0.0")
        asset = dep["latest"]["assets"][0]
        self.assertEqual(
            asset,
            {
                "name": "a.zip",
                "size": 1,
                "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
            },
        )


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
