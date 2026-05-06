import unittest

from release_mirror.manifest import (
    build_asset_key,
    build_mirror_url,
    build_public_asset_url,
    bundles_equivalent,
    to_public_bundle,
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

    def test_build_mirror_url(self) -> None:
        github_url = "https://github.com/owner/repo/releases/download/v1/a.zip"
        self.assertEqual(
            build_mirror_url(github_url),
            "https://gh-proxy.org/https://github.com/owner/repo/releases/download/v1/a.zip",
        )
        self.assertIsNone(build_mirror_url(""))


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
                                        "github_url": "https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
                                        "mirror_url": "https://gh-proxy.org/https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
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
                                        "github_url": "https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
                                        "mirror_url": "https://gh-proxy.org/https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
                                    }
                                ],
                            },
                        }
                    },
                }
            },
        }
        self.assertTrue(bundles_equivalent(a, b))

    def test_to_public_bundle_includes_multi_urls(self) -> None:
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
        asset = dep["latest"]["assets"][0]
        self.assertEqual(
            asset,
            {
                "name": "a.zip",
                "size": 1,
                "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
                "github_url": "https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
                "mirror_url": "https://gh-proxy.org/https://github.com/owner/repo/releases/download/v1.0.0/a.zip",
            },
        )

    def test_to_public_bundle_handles_empty_download_url(self) -> None:
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
                                        "download_url": "",
                                    }
                                ],
                            },
                        }
                    },
                }
            },
        }
        public = to_public_bundle(internal)
        asset = public["projects"]["demo"]["dependencies"]["tool"]["latest"]["assets"][0]
        self.assertIsNone(asset["github_url"])
        self.assertIsNone(asset["mirror_url"])


if __name__ == "__main__":
    unittest.main()
