import unittest

from release_mirror.github_api import filter_assets, select_latest_stable_release


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


if __name__ == "__main__":
    unittest.main()
