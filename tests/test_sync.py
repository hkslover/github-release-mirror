import unittest
from pathlib import Path
import tempfile

from release_mirror.sync import (
    select_latest_and_previous,
    filter_assets,
    build_asset_key,
    build_public_asset_url,
    manifests_equivalent,
    to_public_manifest,
    load_dependencies,
    SyncError,
)


class SelectReleasesTest(unittest.TestCase):
    def test_selects_latest_and_previous_stable_releases(self) -> None:
        releases = [
            {"tag_name": "v3.0.0-rc1", "draft": False, "prerelease": True},
            {"tag_name": "v2.1.0", "draft": False, "prerelease": False},
            {"tag_name": "v2.0.0", "draft": False, "prerelease": False},
            {"tag_name": "v1.9.0", "draft": False, "prerelease": False},
        ]
        latest, previous = select_latest_and_previous(releases)
        self.assertEqual(latest["tag_name"], "v2.1.0")
        self.assertEqual(previous["tag_name"], "v2.0.0")

    def test_handles_single_stable_release(self) -> None:
        releases = [
            {"tag_name": "v1.0.0", "draft": False, "prerelease": False},
        ]
        latest, previous = select_latest_and_previous(releases)
        self.assertEqual(latest["tag_name"], "v1.0.0")
        self.assertIsNone(previous)


class FilterAssetsTest(unittest.TestCase):
    def test_filters_assets_by_regex_patterns(self) -> None:
        assets = [
            {"name": "tool-linux-amd64.tar.gz", "size": 100},
            {"name": "tool-darwin-arm64.tar.gz", "size": 200},
            {"name": "checksum.txt", "size": 50},
        ]
        filtered = filter_assets(assets, [r"linux-amd64", r"darwin-arm64"])
        self.assertEqual([a["name"] for a in filtered], [
            "tool-linux-amd64.tar.gz",
            "tool-darwin-arm64.tar.gz",
        ])

    def test_invalid_regex_raises_sync_error(self) -> None:
        assets = [{"name": "tool-linux-amd64.tar.gz", "size": 100}]
        with self.assertRaises(SyncError):
            filter_assets(assets, [r"("])


class UrlAndKeyTest(unittest.TestCase):
    def test_build_asset_key_uses_immutable_release_path(self) -> None:
        key = build_asset_key("owner/repo", "v1.2.3", "tool linux amd64.tar.gz")
        self.assertEqual(key, "owner/repo/v1.2.3/tool%20linux%20amd64.tar.gz")

    def test_build_public_asset_url_strips_double_slash(self) -> None:
        url = build_public_asset_url(
            "https://downloads.example.com/", "owner/repo/v1.2.3/a.zip"
        )
        self.assertEqual(url, "https://downloads.example.com/owner/repo/v1.2.3/a.zip")


class ManifestComparisonTest(unittest.TestCase):
    def test_equivalent_manifest_ignores_generated_at(self) -> None:
        a = {
            "generated_at": "2026-05-05T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": [
                {
                    "repo": "owner/repo",
                    "latest": {"tag": "v1", "assets": []},
                    "previous": None,
                }
            ],
        }
        b = {
            "generated_at": "2026-05-06T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": [
                {
                    "repo": "owner/repo",
                    "latest": {"tag": "v1", "assets": []},
                    "previous": None,
                }
            ],
        }
        self.assertTrue(manifests_equivalent(a, b))

    def test_public_manifest_strips_internal_asset_fields(self) -> None:
        internal = {
            "generated_at": "2026-05-05T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": [
                {
                    "repo": "owner/repo",
                    "latest": {
                        "tag": "v1",
                        "published_at": "2026-05-05T00:00:00Z",
                        "assets": [
                            {
                                "name": "a.zip",
                                "size": 1,
                                "url": "https://downloads.example.com/owner/repo/v1/a.zip",
                                "key": "owner/repo/v1/a.zip",
                                "download_url": "https://github.com/owner/repo/releases/download/v1/a.zip",
                            }
                        ],
                    },
                    "previous": None,
                }
            ],
        }
        public = to_public_manifest(internal)
        project = public["projects"][0]
        self.assertEqual(project["latest_tag"], "v1")
        self.assertIsNone(project["previous_tag"])
        self.assertEqual(project["latest"]["tag"], "v1")
        self.assertEqual(project["latest"]["tag_name"], "v1")
        asset = public["projects"][0]["latest"]["assets"][0]
        self.assertEqual(asset, {
            "name": "a.zip",
            "size": 1,
            "url": "https://downloads.example.com/owner/repo/v1/a.zip",
        })


class ConfigValidationTest(unittest.TestCase):
    def test_invalid_repo_format_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "deps.yaml"
            config.write_text(
                "dependencies:\n  - repo: invalid-repo-format\n    include_patterns: []\n",
                encoding="utf-8",
            )
            with self.assertRaises(SyncError):
                load_dependencies(config)


if __name__ == "__main__":
    unittest.main()
