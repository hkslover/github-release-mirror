# Release Mirror (GitHub -> R2 -> Pages)

## What it does

- Pulls stable GitHub releases (`draft=false`, `prerelease=false`) from repos defined in `mirror/deps.yaml`.
- Keeps only `latest + previous` release assets in R2.
- Builds a single `manifest.json` for your client.
- Publishes `manifest.json` to `mirror-pages` branch for Cloudflare Pages.

## Required GitHub Secrets

- `GH_RELEASE_TOKEN`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

Optional (for immediate manifest cache refresh):

- `CF_API_TOKEN`
- `CF_ZONE_ID`
- `CF_MANIFEST_URL`

## Cache Strategy

### R2 asset cache headers

All mirrored release assets are uploaded with:

- `Cache-Control: public, max-age=31536000, immutable`

This is safe because object keys are immutable version paths:

- `{owner}/{repo}/{tag}/{asset}`

### Manifest cache headers

`manifest.json` is served by Pages with:

- `Cache-Control: public, max-age=60`

Configured via `mirror/pages/_headers`.

## Cloudflare Dashboard Setup (one-time)

1. Bind your R2 bucket to a **custom domain** (do not use `r2.dev` for production downloads).
2. Create Cache Rules for release asset paths to make them cache-eligible.
3. Enable Smart Tiered Cache.
4. If release files are very large, confirm your plan's cacheable object-size limits.

## Local Dry Run

```bash
python -m pip install -r requirements.release-mirror.txt
R2_PUBLIC_BASE_URL="https://downloads.example.com" \
GH_RELEASE_TOKEN="ghp_xxx" \
python scripts/sync_releases.py \
  --deps mirror/deps.yaml \
  --output-manifest out/manifest.json \
  --result-json out/sync-result.json \
  --dry-run
```

## Manifest shape

`manifest.json` contains:

- `generated_at`
- `base_download_url`
- `projects[].repo`
- `projects[].latest`
- `projects[].previous`
- `assets[].name`
- `assets[].url`
- `assets[].size`

