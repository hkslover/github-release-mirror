import unittest

from release_mirror.errors import SyncError
from release_mirror.r2 import sync_r2_assets


class R2SyncValidationTest(unittest.TestCase):
    def test_missing_download_url_raises_sync_error_before_network(self) -> None:
        desired_internal_manifest = {
            "projects": {
                "demo": {
                    "dependencies": {
                        "tool": {
                            "latest": {
                                "assets": [
                                    {
                                        "name": "a.zip",
                                        "size": 1,
                                        "key": "demo/owner/repo/v1.0.0/a.zip",
                                        "download_url": "",
                                        "url": "https://downloads.example.com/demo/owner/repo/v1.0.0/a.zip",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }

        with self.assertRaises(SyncError):
            sync_r2_assets(
                desired_internal_manifest=desired_internal_manifest,
                existing_public_bundle={},
                github_token=None,
                r2_endpoint="https://example.invalid",
                r2_access_key_id="x",
                r2_secret_access_key="y",
                r2_bucket="z",
            )


if __name__ == "__main__":
    unittest.main()
