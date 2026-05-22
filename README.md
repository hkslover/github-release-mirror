# Release Mirror Template

把多个 GitHub 仓库的 Release 资产自动同步到 Cloudflare R2，并通过 GitHub Pages 发布统一 manifest，给客户端做版本发现与多下载源分发。

## 这个模板解决什么问题

- 依赖项目更新频繁，但你的主程序不需要频繁发版。
- GitHub 直连在部分地区不稳定。
- 你希望客户端拿到同一份清单，同时支持：
  - R2 CDN 地址
  - GitHub 官方地址
  - 国内代理镜像地址（`https://gh-proxy.org/` 前缀）

## 核心特性

- 多项目：`projects.yaml` 支持多个 `project`，每个项目多个 `dependency`。
- 仅稳定版：自动忽略 `draft` / `prerelease`。
- latest-only：每个依赖只保留最新版本资产。
- 三种下载地址同时输出：
  - `url`（R2）
  - `github_url`（GitHub 官方）
  - `mirror_url`（`https://gh-proxy.org/{github_url}`）
- 自动发布到 `mirror-pages` 分支（GitHub Pages）。
- 自动维护 `CNAME`（可选）。

## 工作流概览

1. 读取 `mirror/projects.yaml`
2. 拉取 GitHub Release 元信息
3. 计算目标 manifest（`index.json + {project_id}.json`）
4. 与上次发布内容比较
5. 有变化才执行：
   - 上传新增资产到 R2
   - 删除过期资产
   - 发布新 manifest 到 `mirror-pages`

## 5 分钟快速开始

### 1) 配置项目

编辑 `mirror/projects.yaml`（可参考 `mirror/projects.example.yaml`）：

```yaml
projects:
  - id: cs2-highlight-tool-v2
    name: cs2-highlight-tool-v2
    enabled: true
    ads:
      version: "1.0"
      items:
        - id: sponsor-001
          enabled: true
          placement: main_steps_top_banner
          click_url: https://sponsor.example.com/landing
          sponsor: Sponsor Name
          title: Sponsored
          rich_html: "<p>推广文案 <strong>支持基础标签</strong></p>"
          image_url: https://cdn.example.com/banner-001.jpg
          image_alt: Sponsor banner
    dependencies:
      - id: advancedfx
        name: advancedfx
        repo: advancedfx/advancedfx
        enabled: true
        include_patterns:
          - "^hlae_\\d+(?:_\\d+)*\\.zip$"
```

字段规则：

- `project.id`：全局唯一，建议 `a-zA-Z0-9._-`
- `dependency.id`：同一 project 内唯一
- `repo`：必须是 `owner/name`
- `include_patterns`：正则列表，按资产文件名过滤
- `projects[].ads`：可选；存在时 `version` 必填，`items` 默认为空列表
- `ads.items[*]` 必填字段：`id / placement / click_url / sponsor / title / rich_html / image_url / image_alt`
- `ads.items[*].enabled: false` 会在生成 manifest 时被过滤
- `ads.updated_at` 由系统维护：广告内容不变则复用旧值，内容变化时自动刷新

### 2) 配置 GitHub Secrets

仓库路径：`Settings -> Secrets and variables -> Actions`

必填：

- `GH_RELEASE_TOKEN`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

选填：

- `PAGES_CUSTOM_DOMAIN`（例如 `updates.example.com`）

### 3) 启用 GitHub Pages

1. `Settings -> Pages`
2. Source 选择 `Deploy from a branch`
3. Branch 选择 `mirror-pages`，目录 `/ (root)`
4. 如果用自定义域名：
   - 在 Pages 里设置 Custom domain
   - 同时配置 `PAGES_CUSTOM_DOMAIN`（避免分支覆盖时丢失 CNAME）

### 4) 运行一次 Workflow

进入 `Actions -> release-mirror -> Run workflow` 手动触发一次。

## manifest 结构

### `index.json`

```json
{
  "generated_at": "2026-05-06T00:00:00Z",
  "base_download_url": "https://downloads.example.com",
  "projects": {
    "cs2-highlight-tool-v2": {
      "name": "cs2-highlight-tool-v2",
      "manifest": "cs2-highlight-tool-v2.json"
    }
  }
}
```

### `{project_id}.json`

```json
{
  "generated_at": "2026-05-06T00:00:00Z",
  "base_download_url": "https://downloads.example.com",
  "project": {
    "id": "cs2-highlight-tool-v2",
    "name": "cs2-highlight-tool-v2"
  },
  "ads": {
    "version": "1.0",
    "updated_at": "2026-05-06T00:00:00Z",
    "items": [
      {
        "id": "sponsor-001",
        "enabled": true,
        "placement": "main_steps_top_banner",
        "click_url": "https://sponsor.example.com/landing",
        "sponsor": "Sponsor Name",
        "title": "Sponsored",
        "rich_html": "<p>推广文案 <strong>支持基础标签</strong></p>",
        "image_url": "https://cdn.example.com/banner-001.jpg",
        "image_alt": "Sponsor banner"
      }
    ]
  },
  "dependencies": {
    "advancedfx": {
      "name": "advancedfx",
      "repo": "advancedfx/advancedfx",
      "latest_tag": "v1.2.3",
      "latest": {
        "tag": "v1.2.3",
        "tag_name": "v1.2.3",
        "published_at": "2026-05-06T00:00:00Z",
        "assets": [
          {
            "name": "a.zip",
            "size": 123,
            "url": "https://downloads.example.com/...",
            "github_url": "https://github.com/.../a.zip",
            "mirror_url": "https://gh-proxy.org/https://github.com/.../a.zip"
          }
        ]
      }
    }
  }
}
```

下载字段含义：

- `url`：R2 地址（兼容旧客户端）
- `github_url`：GitHub 官方下载地址
- `mirror_url`：国内代理镜像地址

## 本地调试

安装依赖：

```bash
python3 -m pip install -r requirements.release-mirror.txt
```

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

只做 dry-run（不上传/删除 R2）：

```bash
R2_PUBLIC_BASE_URL="https://downloads.example.com" \
GH_RELEASE_TOKEN="ghp_xxx" \
python3 scripts/sync_releases.py \
  --projects mirror/projects.yaml \
  --output-dir out/pages \
  --result-json out/sync-result.json \
  --dry-run
```

## 项目结构

```text
.github/workflows/release-mirror.yml
mirror/projects.yaml
scripts/sync_releases.py
src/release_mirror/config.py
src/release_mirror/github_api.py
src/release_mirror/manifest.py
src/release_mirror/r2.py
src/release_mirror/orchestrator.py
src/release_mirror/sync.py
tests/test_config.py
tests/test_github_api.py
tests/test_manifest.py
tests/test_r2.py
```

## FAQ

### 1) 已经是最新版本，还会上传 R2 吗？

不会。只有 manifest 内容变化时才会做 R2 上传/删除。

### 2) `R2_ACCESS_KEY_ID` 和 `R2_SECRET_ACCESS_KEY` 是同一个吗？

不是。它们是一对凭据，必须分别配置。

### 3) 只在 Pages UI 里设置域名够不够？

不完全够。因为发布分支会被工作流重写，建议同时设置 `PAGES_CUSTOM_DOMAIN`，确保 `CNAME` 持续存在。
