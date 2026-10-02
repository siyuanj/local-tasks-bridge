# 参与贡献

[English](CONTRIBUTING.md) · **简体中文**

感谢你帮助改进 Local Tasks Bridge！本项目有意保持保守：正确性、数据安全、隐私和可恢复性优先于新功能。范围小、目标明确并附带测试的改动最容易被接受。

## 报告问题

- 请先搜索已有的问题，并用最新的发布版或 `main` 再试一次。
- 请使用问题报告模板。说明你做了什么、预期是什么、实际发生了什么，并附上 `ltb version`、macOS 版本、Mac 类型（Apple 芯片或 Intel）以及登录方式。
- 请分享 `ltb doctor` 的输出或“拷贝诊断信息”的内容，而不是日志。在你发布的任何内容中，删除提醒事项和任务的标题、备注、邮箱地址、账号标识、本地路径、令牌和 OAuth 响应。
- 安全问题请按 [SECURITY.md](SECURITY.md#安全政策简体中文) 私下报告，切勿公开提交。

## 开发环境

你需要一台 Mac，并安装：

- **Xcode 命令行工具**（`xcode-select --install`），它提供 `swiftc` 和 Python 3；不需要完整的 Xcode；
- **Python 3.9 或更高版本**（`python3 --version`）。引擎支持 3.9——也就是 macOS 命令行工具自带的版本——所以请不要使用更新的语言特性。

可选：用于 `make lint` 的 `shellcheck` 和 `actionlint`（`brew install shellcheck actionlint`）。

```bash
git clone https://github.com/siyuanj/local-tasks-bridge.git
cd local-tasks-bridge
make help
```

## make 目标

| 目标 | 作用 |
| --- | --- |
| `make test` | 运行所有 Python 测试——单元测试和端到端测试。离线运行，不接触任何真实数据 |
| `make test-e2e` | 只运行端到端测试（`tests/test_e2e*.py`）：在临时的 `HOME` 中，让真实的引擎命令行对接运行在 `127.0.0.1` 上的模拟 Google OAuth/Tasks 服务器和模拟的提醒事项辅助程序 |
| `make lint` | 对所有 shell 脚本用 macOS 自带的 bash 3.2 做 `bash -n` 检查并运行 `shellcheck`，对工作流运行 `actionlint`，并检查所有 Python 文件的语法 |
| `make helpers` | 把两个提醒事项辅助程序编译到 `build/helpers/` |
| `make app` | 为本机架构构建 `build/Local Tasks Bridge.app`（不内置 Python） |
| `make app-universal` | 构建通用（arm64 + x86_64）版 App |
| `make python` | 下载并校验内置的 Python，放到 `build/python/` |
| `make package` | 在 `dist/` 中生成发布用的 zip、`SHA256SUMS` 和 `release-manifest.json` |
| `make install` | 构建当前源码，并用 `install.sh` 安装到 `~/Applications`（可通过 `INSTALL_ARGS="--embed-python --no-open"` 等传递参数） |
| `make uninstall` | 移除已安装的 App、它的登录项和 `ltb` 链接 |
| `make clean` | 删除构建产物和 `dist/` |

`scripts/test-install.sh` 以封闭方式测试 `install.sh`（临时 `HOME`、本地发布文件，并用替身程序代替 `open`、`launchctl` 等）。修改安装脚本时请运行它。

不需要构建任何东西，就可以在源码目录中直接运行引擎；运行过 `make helpers` 后它会使用 `build/helpers/`，否则会用 `swift` 解释执行 Swift 源文件：

```bash
python3 -B engine/local_tasks_bridge.py --config ~/ltb-dev/config.json status
```

**注意：** `sync`、`auth`、`approvals apply`、`migrate` 或 `agent install` 这类命令会作用于真实的账号和你的登录项。请使用单独的配置文件夹和测试列表——更好的办法是使用端到端测试工具。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `engine/local_tasks_bridge.py` | 同步引擎和 `ltb` 命令行（Python，仅标准库） |
| `macos/App/` | 菜单栏 App（Swift） |
| `macos/Helpers/` | EventKit 辅助程序 `RemindersExport.swift` 和 `RemindersApply.swift` |
| `macos/Resources/` | `Info.plist`、权限声明（entitlements）、`bin/ltb` 包装脚本、`en.lproj` 和 `zh-Hans.lproj` |
| `tests/` | 单元测试和回归测试（`test_engine.py`、`test_local_safety.py`），以及端到端场景（`test_e2e_sync.py`） |
| `tests/e2e/` | 端到端测试工具：模拟 Google 服务器和模拟提醒事项辅助程序 |
| `scripts/` | 构建、打包、下载 Python、安装脚本测试，以及发布源码检查 |
| `site/` | 官网：中英文的产品主页和隐私政策，纯 HTML，发布到 GitHub Pages |
| `promo/` | 宣传视频，用 Remotion 制作；每个功能是一个场景（见 `promo/README.md`） |
| `install.sh` | 安装与卸载脚本 |
| `docs/` | 中英文文档；[app-engine-contract.md](docs/app-engine-contract.md) 是 App 与引擎之间的接口 |

## 改动规则

1. **任何同步行为的改动都必须附带回归测试**，而且这个测试在没有该改动时会失败。请先用合成数据复现问题。
2. **绝不削弱任何安全防护或隐私保护**——包括删除上限与确认流程、不含删除的首次同步、空源保护、账号绑定、写入后核对、私密文件权限，以及让标题不出现在 `status.json`、磁盘日志和命令行参数中——除非拉取请求说明了安全上的理由，并且维护者同意。
3. **只使用合成数据。** 测试绝不能读写真实的提醒事项、Google Tasks、OAuth 凭据、`~/.config`、`~/Library` 或 launchd。请使用临时目录、测试专用的覆盖项（`LTB_TASKS_API`、`LTB_OAUTH_*_URL`、`LTB_REMINDERS_EXPORTER`、`LTB_REMINDERS_APPLY`、`LTB_BUNDLED_OAUTH_CLIENT`、`LTB_LAUNCH_AGENTS_DIR`、`LTB_NO_LAUNCHCTL=1`、`LTB_LOG_DIR`）、`example.invalid` 邮箱地址和一眼就能看出是假的标识符。
4. **每一条面向用户的文字都要有英文和简体中文两个版本。** 引擎中使用 `tr("English", "中文")`；App 中使用 `NSLocalizedString`，并在 `en.lproj` 和 `zh-Hans.lproj` 中都添加条目。文档页面成对出现（`page.md` 和 `page.zh-CN.md`），两个都要更新。请使用 Apple 的官方中文术语（提醒事项、系统设置、隐私与安全性、登录项、小组件）。日志和机器可读的输出保持英文。
5. **遵守接口合同。** 修改命令、JSON 输出、退出码或文件时，请在同一个拉取请求中更新 [docs/app-engine-contract.md](docs/app-engine-contract.md) 以及引擎和 App 两边的代码。
6. **不引入新的依赖**（引擎只用标准库），也不连接 Google OAuth 和 Tasks 端点以外的网络地址。不做遥测。
7. **仓库中不放任何密钥或个人数据**——不放 OAuth 客户端、令牌、同步状态、日志、导出数据或真实的任务标题。`.gitignore` 能帮上忙，但提交前请检查 `git status`。

## 拉取请求

- 每个拉取请求只包含一项行为改动，从 `main` 创建分支。
- 按模板填写：改了什么；如何验证（`make test`、`make lint`；改动 `macos/`、`scripts/` 或 `install.sh` 时运行 `make app`；改动安装脚本时运行 `scripts/test-install.sh`）；对已安装的 App、登录项或用户数据的影响，以及回退方法。
- 在 [CHANGELOG.md](CHANGELOG.md) 的 `## [Unreleased]` 下添加一条记录。
- CI 必须全部通过。

提交贡献即表示你同意你的贡献以 [MIT 许可证](LICENSE)授权。参与本项目请遵守[行为准则](CODE_OF_CONDUCT.md#行为准则简体中文)。
