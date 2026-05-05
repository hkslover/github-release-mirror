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
    parser.add_argument("--deps", default="mirror/deps.yaml", help="Path to dependency config YAML")
    parser.add_argument(
        "--output-manifest",
        default="out/manifest.json",
        help="Path to generated manifest.json",
    )
    parser.add_argument(
        "--previous-manifest",
        default=None,
        help="Path to previous manifest.json for change detection",
    )
    parser.add_argument(
        "--result-json",
        default="out/sync-result.json",
        help="Path to write structured sync result",
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
            deps_path=args.deps,
            output_manifest_path=args.output_manifest,
            previous_manifest_path=args.previous_manifest,
            dry_run=args.dry_run,
        )
        write_json(args.result_json, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SyncError as exc:
        print(f"[sync-error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
