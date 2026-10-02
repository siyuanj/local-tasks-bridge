# 发布流程（维护者）

[English](releasing.md) · **简体中文**

本页供维护者使用，内容包括：版本号、发布新版本、GitHub 密钥、共享客户端的 Google OAuth 验证、Tasks API 配额、公开仓库前的检查清单，以及将来的 Homebrew tap。

## 版本号

Local Tasks Bridge 遵循[语义化版本](https://semver.org/lang/zh-CN/)：

- **主版本号（MAJOR）**：用户或脚本所依赖的东西发生不兼容的变化时递增，例如 `config.json` 和 `state.json` 的结构或含义、`ltb` 的 JSON 输出和退出码（见[接口合同](app-engine-contract.md)）、文件位置，或不再支持某个 macOS 版本。
- **次版本号（MINOR）**：新增功能，且现有安装仍能正常工作。
- **修订号（PATCH）**：修复问题。

版本号出现在三个地方，必须保持一致：

| 位置 | 示例 |
| --- | --- |
| `VERSION`（仓库根目录） | `1.0.0` |
| `engine/local_tasks_bridge.py` 中的 `__version__` | `__version__ = "1.0.0"` |
| `CHANGELOG.md` 中的标题 | `## [1.0.0] - 2026-10-01` |

`scripts/build-app.sh` 会把版本号写入 App 的 `Info.plist`；如果 `VERSION` 与 `__version__` 不一致，或构建出的 App 报告了别的版本号，`scripts/package-release.sh` 会拒绝打包。

## 发布新版本

1. **从 CI 全部通过的 `main` 开始。** CI 会在 Python 3.9、3.12 和 3.13 上运行单元测试和端到端测试，检查脚本和工作流（使用固定版本的工具；缺少工具时检查即失败，`LINT_REQUIRE=1`），并在 macOS 上构建 App 并做冒烟测试。
2. **在分支上准备发布**（`release/vX.Y.Z`）：
   - 设置 `VERSION` 和 `engine/local_tasks_bridge.py` 中的 `__version__`；
   - 把 `CHANGELOG.md` 中 `## [Unreleased]` 下的条目移到新的 `## [X.Y.Z] - YYYY-MM-DD` 一节，并更新文末的比较链接——这一节会成为发布说明；
   - 如果行为有变化，同步更新文档（中英文两版）；
   - 运行 `make lint test`。
3. **合并**这个拉取请求到 `main`。
4. **可以先在本地构建一次**，尽早发现打包问题：`make package` 会在 `dist/` 中生成两个 zip、`SHA256SUMS` 和 `release-manifest.json`（记录构建了什么、来自哪个提交、如何构建）。
5. **先检查源码，再打标签并推送。** 只有当前检出是干净的 `main`，并且 `HEAD` 与 `origin/main`、GitHub 上实时的 `main` 以及你审核过的提交完全一致时，发布源码检查才会通过：

   ```bash
   git switch main && git pull --ff-only
   DEPLOY_EXPECTED_COMMIT="$(git rev-parse HEAD)" scripts/check-release-source.sh
   git tag -a vX.Y.Z -m "Local Tasks Bridge X.Y.Z"
   git push origin vX.Y.Z
   ```

推送的标签会启动 `.github/workflows/release.yml`；对于已有的标签，也可以手动启动这个工作流（Actions → Release → *Run workflow*）。它会：

1. 只接受严格符合 `vX.Y.Z` 格式、并且位于 `main` 上的提交的标签，并检查 `VERSION` 和引擎的 `__version__` 都等于 `X.Y.Z`；
2. 用 `.github/scripts/release-notes.sh` 从 `CHANGELOG.md` 的 `## [X.Y.Z]` 一节提取发布说明——这一节缺失或为空时，发布会停止；
3. 分别用 macOS 系统自带的 Python 和内置 Python 运行测试，并运行安装脚本和发布源码检查的自测；
4. 如果三个 `MACOS_*` 密钥都存在，就把 Developer ID 证书导入一个临时钥匙串（否则构建为临时签名）；如果三个 Apple 密钥都存在，就进行公证；
5. 使用 `LTB_OAUTH_CLIENT_JSON` 中的共享 OAuth 客户端运行 `scripts/package-release.sh --arch all`：生成两种架构、内置 Python 的 App，以及 `SHA256SUMS` 和 `release-manifest.json`。缺少这个密钥时，构建中不含共享客户端，任务摘要中会显示警告；如果仓库变量 `LTB_REQUIRE_SHARED_CLIENT` 为 `true`，发布会直接失败；
6. 安装 Rosetta，并在一个临时的个人目录中用 `install.sh` 对两个 zip 做冒烟测试——标签构建中，无法运行的冒烟测试会让发布失败；
7. 拒绝覆盖已存在的发布，先把两个 zip、`SHA256SUMS` 和 `release-manifest.json` 上传到一个草稿发布，然后再正式发布。

之后，在宣布之前请先**测试已发布的版本**，最好在另一个 macOS 用户账号中进行：一行命令安装（它安装的是 GitHub 标记为 *Latest* 的版本）、浏览器下载加 Gatekeeper 确认的流程、用 `shasum -a 256` 与 `SHA256SUMS` 核对、用两种登录方式和测试列表分别走一遍设置向导、从上一个版本升级（设置和同步对应关系都应保留）、“检查更新…”，以及卸载。

如果发布后发现问题，请删除这个 GitHub Release 和标签，在 `main` 上修复后发布一个新的修订版本。切勿替换已发布版本的文件：用户和 `SHA256SUMS` 都依赖它们保持不变。

## GitHub 密钥

位置：Settings → Secrets and variables → Actions。

| 密钥 | 用途 |
| --- | --- |
| `LTB_OAUTH_CLIENT_JSON` | 维护者的**桌面应用**类型 OAuth 客户端“Local Tasks Bridge”的完整 JSON 文件（`{"installed": {…}}`）。工作流会把它放入 App，作为 `Contents/Resources/oauth_client.json`。 |
| `MACOS_CERTIFICATE_P12_BASE64` | 将来使用：Developer ID Application 证书及私钥，导出为 `.p12` 后做 base64 编码 |
| `MACOS_CERTIFICATE_PASSWORD` | 将来使用：该 `.p12` 的密码 |
| `MACOS_SIGN_IDENTITY` | 将来使用：签名身份，例如 `Developer ID Application: Siyuan Jiang (TEAMID1234)` |
| `APPLE_ID` | 将来使用：用于公证的 Apple ID |
| `APPLE_TEAM_ID` | 将来使用：Apple 开发者团队 ID |
| `APPLE_APP_PASSWORD` | 将来使用：该 Apple ID 的 App 专用密码（appleid.apple.com →“登录与安全”→“App 专用密码”） |

仓库变量（Settings → Secrets and variables → Actions → Variables）：`LTB_REQUIRE_SHARED_CLIENT=true` 会让缺少 `LTB_OAUTH_CLIENT_JSON` 的发布直接失败，而不只是警告。

`scripts/package-release.sh` 从 `LTB_OAUTH_CLIENT_JSON`（或 `LTB_OAUTH_CLIENT_FILE` 指定的文件路径）读取客户端，用 `LTB_SIGN_IDENTITY` 签名（默认为 `-`，即临时签名），并在设置 `LTB_NOTARIZE=1` 以及 `APPLE_ID`、`APPLE_TEAM_ID`、`APPLE_APP_PASSWORD` 后进行公证和装订（staple）。它从不打印这些值。

**切勿提交 OAuth 客户端 JSON。** `.gitignore` 已经排除了 `client_secret*.json` 和 `credentials.json`，但仍请检查 `git status`。在 Google 看来，桌面应用的客户端密钥并不是真正的机密——每一份 App 中都带着它——但把它留在仓库之外，可以减少对共享配额的滥用，也让轮换变得简单：在 Google Cloud 控制台中为该客户端添加新的密钥，更新 GitHub 密钥，发布新版本，等用户都更新后再删除旧密钥。

**Developer ID（以后）。** 使用 Developer ID（需加入 Apple Developer Program）签名并公证后，Gatekeeper 提示会消失，提醒事项权限在更新后得以保留，钥匙串的访问规则也会变得稳定——这是把 Google 令牌移入钥匙串的前提（见[路线图](roadmap.md)）。发布工作流和 `package-release.sh` 已经为此做好准备：添加上面的密钥后，构建会启用 hardened runtime 签名，用 `xcrun notarytool` 公证并装订。

## 共享客户端的 Google OAuth 验证

共享客户端位于维护者的 Google Cloud 项目中，状态为**正式版（In production）**但**未经验证**。这意味着：

- 用户会在授权页面上看到“Google 未验证此应用”；
- 在通过验证之前，Google 在项目的整个生命周期内最多允许 **100 位用户**（计数显示在 Google Auth Platform → Audience → OAuth user cap 中，无法重置）；
- Google Tasks API 的权限范围 `https://www.googleapis.com/auth/tasks` 属于**敏感**（而非受限）范围，所以验证需要审核，但不需要第三方安全评估。

要解除上限并去掉警告：

1. **品牌信息。** 在 Google Auth Platform → Branding 中，保留应用名称 *Local Tasks Bridge*，添加徽标（120 × 120 像素）、支持邮箱、首页 `https://siyuanj.github.io/local-tasks-bridge-site/`、隐私政策 `https://siyuanj.github.io/local-tasks-bridge-site/privacy/` 和已获授权的网域 `siyuanj.github.io`。首页必须说明应用的功能、链接到隐私政策，并且无需登录即可公开访问。隐私政策必须说明访问了哪些 Google 数据、如何使用、存储和共享，并包含“有限使用”（Limited Use）声明；仓库中的 [PRIVACY.zh-CN.md](../PRIVACY.zh-CN.md) 就是它的完整版——请让两者都与 App 的实际行为保持一致。
2. **网域所有权。** 使用 Cloud 项目的所有者（Owner）或编辑者（Editor）账号，在 [Google Search Console](https://search.google.com/search-console) 中验证网站。对于 GitHub Pages 网站，可以添加网址前缀资源 `https://siyuanj.github.io/`，并在网站模板中用 HTML 标记的方式验证。如果 Google 坚持要求网域资源，请为这些页面使用自定义域名。
3. **数据访问。** 添加 App 申请的权限范围：`…/auth/tasks`、`openid` 和 `…/auth/userinfo.email`。为 Tasks 权限写一段理由：App 执行双向同步——会创建、编辑、完成和删除任务——所以只读权限不够；数据只在用户自己的 Mac 上处理，从不发送给开发者。
4. **演示视频。** 录一段简短的视频，以“不公开”方式上传到 YouTube。视频应展示：设置向导中选择共享客户端；英文的 Google 授权页面，并且浏览器地址栏中能看到 OAuth 客户端 ID；授予权限的过程；一个任务在两个方向上的同步；以及数据保存在哪里（只在 Mac 上）。
5. **提交**：在 Google Auth Platform → Verification Center 中提交，并及时回复 Google 审核团队的邮件。品牌验证通常需要几个工作日；敏感权限范围的审核可能需要数周。

通过验证后，警告会消失，用户数上限也会解除。之后若修改权限范围、应用名称、徽标或网域，都需要重新验证。

## Google Tasks API 配额

共享客户端的所有用户共用一个项目配额——默认大约**每天 50,000 次请求**。因此，引擎对使用共享客户端的用户最多每 5 分钟向 Google 查询一次，并在空闲轮次中跳过核对读取：同步一个列表的用户每天大约需要 580 次请求，三个列表大约 1,150 次，每一批本机改动再额外消耗几次（见[配额计算](configuration.zh-CN.md#同步间隔与-google-配额)）。因此默认配额只够几十位活跃用户使用。

- 在 APIs & Services → Google Tasks API → Metrics 和 Quotas 中关注用量（`https://console.cloud.google.com/apis/api/tasks.googleapis.com/quotas`），并可以考虑在 Cloud Monitoring 中设置提醒，在达到每日上限之前收到通知。
- 在 Quotas 页面申请提高配额，附上简短的理由（用户数、每位用户的列表数、同步间隔）。即使 Tasks API 本身免费，Google 也可能要求先关联结算账号才批准更高的配额。
- 配额用完后，请求会以 HTTP 429 或 403 失败，直到太平洋时间午夜配额重置；在此期间桥接会报告同步失败，之后会自动恢复。使用自有客户端的用户不受影响。

## 公开仓库前的检查清单

- [ ] **提交历史中的作者邮箱。** 本派生项目的提交带有这台 Mac 上使用的作者邮箱地址，公开仓库就会公开它。要么接受，要么在第一次公开推送之前改写历史（例如用 `git filter-repo --mailmap`），并从此改用 GitHub 的 `noreply` 地址（`git config user.email <id>+siyuanj@users.noreply.github.com`，并在 GitHub 设置中开启 “Keep my email addresses private”）。改写必须在任何人克隆公开仓库之前完成。
- [ ] **扫描完整历史中的密钥**，而不只是当前文件：

      ```bash
      gitleaks git --redact -v .
      trufflehog git file://. --results=verified,unknown
      git log --all --name-only --format= | sort -u \
        | grep -Ei 'client_secret|credentials|token|state\.json|status\.json|\.log$'
      ```

      2026-10-01 的扫描没有发现任何问题；公开之前请再运行一次。
- [ ] **历史中的个人数据：** 在旧提交中搜索绝对路径、真实的任务标题和邮箱地址（例如 `git log -p --all | grep -nE '/Users/[^/]+/'`）。
- [ ] **标签：** 不要推送 `prod/icloud-reminders-google-sync/…` 这类本地部署标签；只推送 `vX.Y.Z` 标签。
- [ ] **链接：** 问题模板中的安全链接（`.github/ISSUE_TEMPLATE/config.yml`）以及所有文档链接都必须指向 `siyuanj/local-tasks-bridge`。
- [ ] **仓库设置：** 描述、网站（`https://siyuanj.github.io/local-tasks-bridge-site/`）、主题标签（`macos`、`apple-reminders`、`google-tasks`、`sync`、`menu-bar-app`）。
- [ ] **安全设置：** 开启 *Private vulnerability reporting*（Settings → Security → Advisories）、Dependabot 警报、密钥扫描（secret scanning）和推送保护（push protection）。
- [ ] **`main` 的分支保护：** 要求通过拉取请求合并且 CI 通过，禁止强制推送。
- [ ] **Actions：** 保持所有 action 固定到完整的提交 SHA，工作流权限保持最小；确保密钥只被标签触发的发布工作流使用。
- [ ] **修改可见性**（Settings → General → Danger Zone）。
- [ ] **发布 v1.0.0**，并在一个全新的 macOS 用户账号中测试一行命令安装和 `install.sh` 的原始网址。
- [ ] **网站页面：** 主页和隐私政策放在独立的公开仓库 [siyuanj/local-tasks-bridge-site](https://github.com/siyuanj/local-tasks-bridge-site)（GitHub Pages，`https://siyuanj.github.io/local-tasks-bridge-site/`）。它们是 Google OAuth 品牌信息中登记的网址，请与 [PRIVACY.zh-CN.md](../PRIVACY.zh-CN.md) 保持一致。

## Homebrew tap（以后）

cask 模板位于 `packaging/homebrew/local-tasks-bridge.rb`。发布某个版本时，用该版本的版本号和校验值生成 cask：

```bash
packaging/homebrew/update-cask.sh --version X.Y.Z --sums path/to/SHA256SUMS
```

默认情况下，脚本使用 `VERSION` 文件和 `dist/SHA256SUMS`，输出到 `dist/local-tasks-bridge.rb`（可用 `--output` 修改）。把结果提交到 tap 仓库（例如 `siyuanj/homebrew-tap`）中，作为 `Casks/local-tasks-bridge.rb`；之后用户就可以用 `brew install --cask siyuanj/tap/local-tasks-bridge` 安装。

这个模板可以用于 1.0 的临时签名构建——由于 Homebrew 会给下载的文件加上隔离标记，它的 caveats 中说明了 Gatekeeper 的处理方法——但最好等构建经过公证后再正式推出 tap。它在 `brew uninstall` 时只会退出 App，只有 `brew uninstall --zap` 才会移除登录项、设置和日志，因此 `brew upgrade` 不会删掉登录项。请修改模板，而不要手写 cask。

