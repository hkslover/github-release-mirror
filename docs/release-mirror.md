# Release Mirror v2 (GitHub -> R2 -> GitHub Pages)

## Overview

- Config source: `mirror/projects.yaml`
- Output: `index.json` + `{project_id}.json` files
- Retention: latest-only per dependency
- R2 object key: `{project_id}/{owner}/{repo}/{tag}/{asset}`

## Workflow behavior

1. Load `projects.yaml`
2. Read previous Pages payload from `mirror-pages` branch
3. Fetch latest stable releases from GitHub API
4. Compare old/new public manifest bundles (ignore `generated_at`)
5. If changed:
   - Upload missing assets to R2
   - Delete stale assets from previous latest tags
   - Publish new Pages payload

## Required environment variables

- `GH_RELEASE_TOKEN`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

Optional:

- `PAGES_CUSTOM_DOMAIN`

## Notes

- `include_patterns` is regex-based and validated during config loading.
- If a dependency has no stable release, `latest` will be `null`.
- CNAME is managed during payload generation to prevent custom-domain loss on branch overwrite.
