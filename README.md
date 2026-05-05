# GitHub Release 镜像到 Cloudflare R2 + GitHub Pages

这个仓库用于自动同步多个 GitHub 开源项目的 **正式版 Release 资产** 到 Cloudflare R2，并通过 GitHub Pages 发布单一 `manifest.json`，供客户端统一拉取版本与下载地址。

适用场景：
- 你的主程序更新频率低，但依赖项目的 release 更新频率高。
- 你希望给国内用户提供更稳定的下载入口（R2 自定义域名 + CDN 缓存）。

## 功能概览

- 自动拉取 `mirror/deps.yaml` 里配置的仓库 release。
- 仅同步 `draft=false` 且 `prerelease=false` 的版本。
- 每个仓库仅保留 `最新 + 上一个` 版本资产。
- 资产上传到 R2 时设置长期缓存头：
  - `Cache-Control: public, max-age=31536000, immutable`
- 自动生成单一 `manifest.json`。
- 将 `manifest.json` 推送到 `mirror-pages` 分支，供 GitHub Pages 直接发布。
- 支持自动维护 `CNAME` 文件（自定义子域名不丢失）。

## 仓库结构

```text
.github/workflows/release-mirror.yml   # GitHub Actions 工作流
mirror/deps.yaml                        # 依赖仓库与资产过滤规则
scripts/sync_releases.py                # 同步入口脚本
src/release_mirror/sync.py              # 核心同步逻辑
tests/test_sync.py                      # 单元测试
```

## 工作流执行流程

1. 读取 `mirror/deps.yaml`
2. 调 GitHub API 拉取 release 元数据
3. 计算每个项目的 `latest + previous`
4. 与 `mirror-pages` 分支当前 `manifest.json` 对比
5. 无变化：结束（不上传，不发布）
6. 有变化：
   - 下载新增资产
   - 上传到 R2（带缓存头）
   - 删除不在保留窗口内的旧资产
   - 生成新的 `manifest.json`
   - 推送到 `mirror-pages` 分支触发 Pages 更新

## 第一步：配置依赖仓库

编辑 `mirror/deps.yaml`：

```yaml
dependencies:
  - repo: owner1/project1
    enabled: true
    include_patterns:
      - "linux-amd64"
      - "darwin-arm64"

  - repo: owner2/project2
    enabled: true
    include_patterns:
      - "\\.zip$"
```

说明：
- `repo` 必须是 `owner/name` 格式。
- `include_patterns` 是正则，匹配资产文件名。
- 正则写错会直接失败（防止误同步）。

## 第二步：配置 GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 添加：

必填：
- `GH_RELEASE_TOKEN`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`

选填（用于 GitHub Pages 自定义域名）：
- `PAGES_CUSTOM_DOMAIN`（可放在 `Secrets` 或 `Variables`，例如 `updates.snowblog.xyz`）

## 第三步：配置 Cloudflare

### 1) R2

- 创建 R2 Bucket。
- 绑定 **自定义域名**（生产环境不建议直接用 `r2.dev`）。
- 该自定义域名应与 `R2_PUBLIC_BASE_URL` 一致。

### 2) 缓存策略建议

- 对 release 资产路径启用缓存（Cache Rules）。
- 开启 Smart Tiered Cache。
- 大文件注意 Cloudflare 套餐的可缓存单文件大小限制。

## 第四步：配置 GitHub Pages

1. 进入仓库 `Settings -> Pages`
2. `Build and deployment` 选择 `Deploy from a branch`
3. Branch 选择 `mirror-pages`，目录选择 `/ (root)`
4. 如果使用自定义子域名：
   - 在 Pages 的 `Custom domain` 填你自己的域名
   - 同时设置 `PAGES_CUSTOM_DOMAIN`，让 workflow 自动保留 `CNAME` 文件
   - 在 Cloudflare DNS 添加 `CNAME` 到 `hkslover.github.io`

## 第五步：触发同步

工作流文件是 `.github/workflows/release-mirror.yml`。

当前触发方式：
- 定时：每天一次（`cron: 0 2 * * *`，UTC 时间）
- 手动：`workflow_dispatch`

你可以在 GitHub Actions 页面手动运行一次验证全流程。

## 本地调试

安装依赖：

```bash
python3 -m pip install -r requirements.release-mirror.txt
```

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

只做 dry-run（不上传 R2，不删除旧资产）：

```bash
R2_PUBLIC_BASE_URL="https://downloads.example.com" \
GH_RELEASE_TOKEN="ghp_xxx" \
python3 scripts/sync_releases.py \
  --deps mirror/deps.yaml \
  --output-manifest out/manifest.json \
  --result-json out/sync-result.json \
  --dry-run
```

## manifest.json 格式（对客户端）

输出是单一总清单，核心字段：

- `generated_at`
- `base_download_url`
- `projects[].repo`
- `projects[].latest_tag`
- `projects[].previous_tag`
- `projects[].latest`
- `projects[].previous`
- `projects[].latest.tag`
- `projects[].latest.tag_name`
- `projects[].assets[].name`
- `projects[].assets[].size`
- `projects[].assets[].url`

注意：内部上传过程用到的 `key/download_url` 不会暴露给客户端。

## 常见问题

### 1) GitHub API 403 rate limit

- 需要配置有效的 `GH_RELEASE_TOKEN`。
- 匿名访问配额很容易被打满。

### 2) 工作流显示成功但没有发布新 manifest

- 通常是“对比后无变化”，这是预期行为。
- 只有检测到内容变化才会推送 `mirror-pages`。

### 3) 自定义域名为什么会“自己消失”？

- 通常是部署覆盖了发布分支里的 `CNAME` 文件。
- 本仓库已支持自动写入/保留 `CNAME`，请设置 `PAGES_CUSTOM_DOMAIN`。

## 参考文档

- 详细说明可见 `docs/release-mirror.md`
