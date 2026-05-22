import unittest

from release_mirror.manifest import (
    build_asset_key,
    build_mirror_url,
    build_public_asset_url,
    bundles_equivalent,
    changed_project_ids,
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

    def test_to_public_bundle_outputs_ads_in_project_manifest_only(self) -> None:
        internal = {
            "generated_at": "2026-05-18T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": {
                "demo": {
                    "id": "demo",
                    "name": "Demo",
                    "ads": {
                        "version": "1.0",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    },
                    "dependencies": {},
                }
            },
        }

        public = to_public_bundle(internal)
        self.assertNotIn("ads", public["index"])
        ads = public["projects"]["demo"]["ads"]
        self.assertEqual(ads["version"], "1.0")
        self.assertEqual(ads["updated_at"], "2026-05-18T00:00:00Z")
        self.assertEqual(len(ads["items"]), 1)

    def test_to_public_bundle_preserves_ads_items_order(self) -> None:
        internal = {
            "generated_at": "2026-05-18T00:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": {
                "demo": {
                    "id": "demo",
                    "name": "Demo",
                    "ads": {
                        "version": "1.0",
                        "items": [
                            {
                                "id": "b-ad",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/b",
                                "sponsor": "Sponsor B",
                                "title": "B",
                                "rich_html": "<p>B</p>",
                                "image_url": "https://cdn.example.com/b.jpg",
                                "image_alt": "B",
                            },
                            {
                                "id": "a-ad",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/a",
                                "sponsor": "Sponsor A",
                                "title": "A",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            },
                        ],
                    },
                    "dependencies": {},
                }
            },
        }

        public = to_public_bundle(internal)
        items = public["projects"]["demo"]["ads"]["items"]
        self.assertEqual([item["id"] for item in items], ["b-ad", "a-ad"])

    def test_to_public_bundle_reuses_ads_updated_at_when_ads_unchanged(self) -> None:
        internal = {
            "generated_at": "2026-05-18T10:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": {
                "demo": {
                    "id": "demo",
                    "name": "Demo",
                    "ads": {
                        "version": "1.0",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    },
                    "dependencies": {},
                }
            },
        }
        previous_public = {
            "projects": {
                "demo": {
                    "ads": {
                        "version": "1.0",
                        "updated_at": "2026-05-17T12:00:00Z",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    }
                }
            }
        }

        public = to_public_bundle(internal, previous_public_bundle=previous_public)
        self.assertEqual(
            public["projects"]["demo"]["ads"]["updated_at"],
            "2026-05-17T12:00:00Z",
        )

    def test_to_public_bundle_refreshes_ads_updated_at_when_ads_changed(self) -> None:
        internal = {
            "generated_at": "2026-05-18T10:00:00Z",
            "base_download_url": "https://downloads.example.com",
            "projects": {
                "demo": {
                    "id": "demo",
                    "name": "Demo",
                    "ads": {
                        "version": "1.0",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored changed",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    },
                    "dependencies": {},
                }
            },
        }
        previous_public = {
            "projects": {
                "demo": {
                    "ads": {
                        "version": "1.0",
                        "updated_at": "2026-05-17T12:00:00Z",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    }
                }
            }
        }

        public = to_public_bundle(internal, previous_public_bundle=previous_public)
        self.assertEqual(
            public["projects"]["demo"]["ads"]["updated_at"],
            "2026-05-18T10:00:00Z",
        )

    def test_bundle_comparison_and_changed_projects_include_ads(self) -> None:
        a = {
            "index": {
                "generated_at": "2026-05-18T00:00:00Z",
                "base_download_url": "https://downloads.example.com",
                "projects": {"demo": {"name": "Demo", "manifest": "demo.json"}},
            },
            "projects": {
                "demo": {
                    "generated_at": "2026-05-18T00:00:00Z",
                    "base_download_url": "https://downloads.example.com",
                    "project": {"id": "demo", "name": "Demo"},
                    "dependencies": {},
                    "ads": {
                        "version": "1.0",
                        "updated_at": "2026-05-18T00:00:00Z",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    },
                }
            },
        }
        b = {
            "index": {
                "generated_at": "2026-05-18T00:00:00Z",
                "base_download_url": "https://downloads.example.com",
                "projects": {"demo": {"name": "Demo", "manifest": "demo.json"}},
            },
            "projects": {
                "demo": {
                    "generated_at": "2026-05-18T00:00:00Z",
                    "base_download_url": "https://downloads.example.com",
                    "project": {"id": "demo", "name": "Demo"},
                    "dependencies": {},
                    "ads": {
                        "version": "1.0",
                        "updated_at": "2026-05-18T00:00:00Z",
                        "items": [
                            {
                                "id": "ad-1",
                                "enabled": True,
                                "placement": "main_steps_top_banner",
                                "click_url": "https://sponsor.example.com/landing",
                                "sponsor": "Sponsor A",
                                "title": "Sponsored changed",
                                "rich_html": "<p>A</p>",
                                "image_url": "https://cdn.example.com/a.jpg",
                                "image_alt": "A",
                            }
                        ],
                    },
                }
            },
        }

        self.assertFalse(bundles_equivalent(a, b))
        self.assertEqual(changed_project_ids(a, b), ["demo"])


if __name__ == "__main__":
    unittest.main()
