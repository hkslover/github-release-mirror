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

    def test_ads_parses_and_filters_disabled_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-enabled
          enabled: true
          placement: main_steps_top_banner
          click_url: https://sponsor.example.com/landing
          image_url: https://cdn.example.com/banner-a.jpg
          image_alt: banner a
        - id: ad-disabled
          enabled: false
          placement: main_entry_popup
          click_url: https://sponsor.example.com/landing-disabled
          image_url: https://cdn.example.com/banner-b.jpg
""".strip()
                + "\n",
                encoding="utf-8",
            )

            projects = load_projects(config)
            self.assertEqual(len(projects), 1)
            ads = projects[0].ads
            self.assertIsNotNone(ads)
            assert ads is not None
            self.assertEqual(ads.version, "1.0")
            self.assertEqual([item.id for item in ads.items], ["ad-enabled"])
            item = ads.items[0]
            self.assertEqual(item.placement, "main_steps_top_banner")
            self.assertEqual(item.image_url, "https://cdn.example.com/banner-a.jpg")
            self.assertEqual(item.image_alt, "banner a")
            # Legacy text-card fields are optional and default to "".
            self.assertEqual(item.sponsor, "")
            self.assertEqual(item.title, "")
            self.assertEqual(item.rich_html, "")

    def test_ad_legacy_text_fields_are_optional_and_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          placement: main_entry_popup
          click_url: https://sponsor.example.com/landing
          image_url: https://cdn.example.com/banner-a.jpg
          sponsor: Sponsor A
          title: Sponsored
          rich_html: "<p>banner-a</p>"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            ads = load_projects(config)[0].ads
            assert ads is not None
            item = ads.items[0]
            self.assertEqual(item.sponsor, "Sponsor A")
            self.assertEqual(item.title, "Sponsored")
            self.assertEqual(item.rich_html, "<p>banner-a</p>")

    def test_ad_placement_must_be_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          placement: sidebar_footer
          click_url: https://sponsor.example.com/landing
          image_url: https://cdn.example.com/banner-a.jpg
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(SyncError):
                load_projects(config)

    def test_ad_image_url_accepts_inline_data_image_uri(self) -> None:
        inline = "data:image/png;base64,iVBORw0KGgo="
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                f"""
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          placement: main_entry_popup
          click_url: https://sponsor.example.com/landing
          image_url: "{inline}"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            ads = load_projects(config)[0].ads
            assert ads is not None
            self.assertEqual(ads.items[0].image_url, inline)

    def test_ad_image_url_rejects_non_image_data_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          placement: main_steps_top_banner
          click_url: https://sponsor.example.com/landing
          image_url: "data:text/html,<script>alert(1)</script>"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(SyncError):
                load_projects(config)

    def test_shipped_projects_yaml_loads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        projects = load_projects(root / "mirror" / "projects.yaml")
        project = next(p for p in projects if p.id == "cs2-highlight-tool-v2")
        assert project.ads is not None
        by_id = {item.id: item for item in project.ads.items}
        self.assertEqual(
            by_id["sponsor-88dog-top-banner"].placement, "main_steps_top_banner"
        )
        self.assertEqual(
            by_id["sponsor-88dog-entry-popup"].placement, "main_entry_popup"
        )
        for item in project.ads.items:
            self.assertEqual(
                item.image_url,
                "https://dl.snowblog.xyz/cs2-highlight-tool-v2/static/"
                + ("88dog_top.png" if item.placement == "main_steps_top_banner" else "88dog_entry.png"),
            )

    def test_ads_missing_placement_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          click_url: https://sponsor.example.com/landing
          image_url: https://cdn.example.com/banner-a.jpg
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(SyncError):
                load_projects(config)

    def test_ads_invalid_url_raises_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "projects.yaml"
            config.write_text(
                """
projects:
  - id: demo
    name: Demo
    dependencies: []
    ads:
      version: "1.0"
      items:
        - id: ad-1
          placement: main_steps_top_banner
          click_url: ftp://sponsor.example.com/landing
          image_url: https://cdn.example.com/banner-a.jpg
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(SyncError):
                load_projects(config)

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
