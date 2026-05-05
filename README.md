# GitHub Release Mirror Template (R2 + GitHub Pages)

这个模板仓库用于同步 GitHub Release 资产到 Cloudflare R2，并发布 manifest 到 GitHub Pages。

## 功能

- 多项目配置：一个仓库可以维护多个 `project`。
- 每个项目支持多个依赖 `dependency`。
- 仅同步稳定版 release（`draft=false` 且 `prerelease=false`）。
- 每个依赖只保留 `latest`（不再保留 previous）。
- R2 资产默认上传缓存头：
  - `Cache-Control: public, max-age=31536000, immutable`
- Pages 发布：
  - `index.json`
  - `{project_id}.json`
  - `CNAME`（可选，自动维护）

## 目录结构

```text
.github/workflows/release-mirror.yml
mirror/projects.yaml
mirror/projects.example.yaml
scripts/sync_releases.py
src/release_mirror/sync.py
tests/test_sync.py
```

## 1) 配置项目

编辑 `mirror/projects.yaml`：

```yaml
projects:
  - id: demo-project
    name: Demo Project
    enabled: true
    dependencies:
      - id: tool-linux
        name: Tool Linux
        repo: owner/tool-repo
        enabled: true
        include_patterns:
          - "linux-amd64"
```

字段说明：

- `project.id`：全局唯一，建议使用 `a-zA-Z0-9._-`。
- `dependency.id`：在同一个 project 内唯一。
- `repo`：必须是 `owner/name`。
- `include_patterns`：正则表达式数组，匹配资产文件名。

## 2) GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 设置：

必填：

- `GH_RELEASE_TOKEN`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

选填：

- `PAGES_CUSTOM_DOMAIN`
  - 例如 `updates.snowblog.xyz`
  - 设置后 workflow 会持续生成/覆盖 `CNAME`，避免 Pages 分支更新时域名丢失

## 3) GitHub Pages 配置

1. 进入 `Settings -> Pages`
2. `Deploy from a branch`
3. Branch 选 `mirror-pages`
4. Folder 选 `/ (root)`
5. 如果要自定义域名：
   - 在 Pages UI 里填写域名
   - 同时建议设置 `PAGES_CUSTOM_DOMAIN`（防覆盖）
   - DNS 配置 `CNAME` 到 `<your-user>.github.io`

## 4) 手动运行测试

```bash
python3 -m pip install -r requirements.release-mirror.txt
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

本地 dry-run（不上传 R2、不删除旧对象）：

```bash
R2_PUBLIC_BASE_URL="https://downloads.example.com" \
GH_RELEASE_TOKEN="ghp_xxx" \
python3 scripts/sync_releases.py \
  --projects mirror/projects.yaml \
  --output-dir out/pages \
  --result-json out/sync-result.json \
  --dry-run
```

## 5) manifest v2 结构

`index.json`：

- `generated_at`
- `base_download_url`
- `projects`（`project_id -> {name, manifest}`）

`{project_id}.json`：

- `generated_at`
- `base_download_url`
- `project.id / project.name`
- `dependencies`（`dependency_id` 做 key）
- `dependencies[dep].latest_tag`
- `dependencies[dep].latest.tag`
- `dependencies[dep].latest.assets[].name/url/size`

## FAQ

### CNAME 必须提交到分支吗？

如果发布分支是由 workflow 重写，建议每次发布都写入 `CNAME`，否则可能被覆盖掉。  
只在 Pages UI 设置域名，不保证分支重建后仍保留。

### `R2_ACCESS_KEY_ID` 和 `R2_SECRET_ACCESS_KEY` 是同一个吗？

不是。它们是一对 S3 API 凭据，必须分别填写。
