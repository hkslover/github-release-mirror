#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make local src importable when running directly.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from release_mirror.sync import SyncError, run_sync, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync GitHub releases to Cloudflare R2 and build manifest")
    parser.add_argument(
        "--projects",
        default="mirror/projects.yaml",
        help="Path to projects config YAML",
    )
    parser.add_argument(
        "--output-dir",
        default="out/pages",
        help="Output directory for index.json and per-project manifests",
    )
    parser.add_argument(
        "--previous-dir",
        default=None,
        help="Directory containing previous pages payload for change detection",
    )
    parser.add_argument(
        "--result-json",
        default="out/sync-result.json",
        help="Path to write structured sync result",
    )
    parser.add_argument(
        "--pages-custom-domain",
        default=None,
        help="Custom domain to write to CNAME (optional)",
    )
    parser.add_argument(
        "--previous-cname-file",
        default=None,
        help="Fallback CNAME file from previous pages payload (optional)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute manifest and detect changes, but skip R2 upload/delete",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = run_sync(
            projects_path=args.projects,
            output_dir=args.output_dir,
            previous_dir=args.previous_dir,
            dry_run=args.dry_run,
            pages_custom_domain=args.pages_custom_domain,
            previous_cname_file=args.previous_cname_file,
        )
        write_json(args.result_json, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SyncError as exc:
        print(f"[sync-error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
