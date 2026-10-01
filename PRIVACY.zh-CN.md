# 隐私政策

[English](PRIVACY.md) · **简体中文**

*自 2026 年 10 月 1 日起生效 · 适用于 Local Tasks Bridge 1.0 及更高版本*

Local Tasks Bridge 是一款在你的 Mac 上运行、在 Apple 提醒事项与 Google Tasks 之间同步的开源软件。本政策用浅白的语言说明它会接触哪些数据、这些数据去往何处，以及你如何掌控它们。简而言之：**你的数据只留在你的 Mac 上，以及 Apple 和 Google 那里，绝不会发送给维护者或任何其他人。**

本政策的公开版本位于 <https://siyuanj.github.io/local-tasks-bridge/privacy/>（英文）。如中英文版本有出入，以英文版为准。

## 由谁负责

Local Tasks Bridge 是由 Siyuan Jiang（[@siyuanj](https://github.com/siyuanj)）维护的开源项目。维护者没有为它运行任何服务器，也不会接收、存储或处理你的任务、提醒事项或凭据。

## 软件会访问什么

**在你的 Mac 上（Apple 提醒事项）。** 你在 macOS 中授权之后，App 可以通过 Apple 的 EventKit 框架读写你的提醒事项。macOS 授予的是所有列表的访问权限；桥接只读写你选中的列表。为了让你选择，它也会读取你所有列表的名称及其所属账号。对每条已同步的提醒事项，它会使用标题、备注、截止日期、完成状态、所在列表，以及匹配所需的标识符和时间戳。

**在你的 Google 账号中（Google Tasks）。** 登录时，你会授予三项权限（OAuth 权限范围）：

| 权限范围 | 用途 |
| --- | --- |
| `https://www.googleapis.com/auth/tasks` | 读取你的任务列表和任务，并创建、更新、完成和删除任务及列表，以保持同步 |
| `openid` | 你的 Google 账号 ID，用于把同步对应关系与你的账号绑定 |
| `email` | 你账号的邮箱地址，用于向你显示当前连接的是哪个账号 |

桥接不会申请任何其他访问权限——不涉及 Gmail、日历、云端硬盘或通讯录。

## 存储了什么，存在哪里

所有内容都保存在你的 Mac 上、你自己的用户账号中：

| 文件 | 内容 |
| --- | --- |
| `~/.config/local-tasks-bridge/config.json` | 你的设置，包括所选列表的名称 |
| `…/token.json` | 你的 Google 登录令牌，其中的 ID 令牌包含你的账号 ID 和邮箱地址 |
| `…/credentials.json` | 你自己的 Google OAuth 客户端（如果导入过） |
| `…/state.json` | 同步对应关系：把每条提醒事项与对应 Google 任务关联起来的标识符和指纹、条目标题和列表名称，以及经过哈希的账号标识 |
| `…/status.json` | 上一次同步的结果：时间、数量和哈希值，不含标题 |
| `…/backups/` | 执行有风险的操作之前，上述文件的备份 |
| `~/Library/Logs/LocalTasksBridge/` | 每次同步做了什么的日志，包含任务标题 |

这些文件夹和文件只有你的 macOS 用户账号可以读取。没有任何内容保存在维护者运营的服务器上——因为根本没有这样的服务器。

桥接还会在每个已同步的 Google 任务的备注末尾添加一小段同步标记（“Synced from Apple Reminders.”、列表名称和两个标识符）。它和任务的其他内容一样，保存在你的 Google 账号中。

## 什么数据发往哪里

- **发往 Google：** 发往 Google 登录端点（`accounts.google.com`、`oauth2.googleapis.com`、`openidconnect.googleapis.com`）和 Google Tasks API（`tasks.googleapis.com`）的请求。为了同步，这些请求会携带已同步条目的内容——标题、带同步标记的备注、截止日期、完成状态和列表名称。它们通过 HTTPS 从你的 Mac 直接发往 Google，或经过你自己配置的代理。
- **发往 Apple：** 通过你 Mac 上的 EventKit 写入的提醒事项更改。之后 iCloud 会按照 Apple 的条款把它们同步到你的其他设备。
- **发往 GitHub，仅在你主动要求时：** “检查更新…”会向 GitHub 的公开 API 查询最新版本，“帮助”会在浏览器中打开 GitHub 页面，安装脚本会从 GitHub 下载 App。和任何网络请求一样，GitHub 能看到你的 IP 地址；但不会发送任何与你的任务有关的内容。
- **发往维护者或其他任何人：** 没有。没有遥测，没有统计分析，没有崩溃报告，没有广告，也没有跟踪。

## 共享的 Google 客户端

发布版可以内置维护者名为“Local Tasks Bridge”的 Google OAuth 客户端，让你无需自己创建就能登录：

- Google 会记录你授权了这个客户端，它会以这个名字出现在你 Google 账号的已连接应用列表中。
- 这个客户端只是向 Google 表明 App 的身份。你的登录令牌是为你生成、保存在你自己 Mac 上的，你的任务数据仍然只在你的 Mac 和 Google 之间传输。维护者无法通过共享客户端访问你的账号或任务。
- 在 Google Cloud 控制台中，维护者能看到项目的汇总数字——例如有多少用户授权了这个客户端、发出了多少 API 请求、有多少失败——但看不到你是谁，也看不到你的任务内容。

如果你愿意，也可以使用[你自己的 Google Cloud 客户端](docs/google-cloud-setup.zh-CN.md)，这样在 Google 看来，App 就是你自己的项目。

## Google API 服务用户数据政策

Local Tasks Bridge 对从 Google API 获取的信息的使用和传输，遵守 [Google API 服务用户数据政策](https://developers.google.com/terms/api-services-user-data-policy)（Google API Services User Data Policy），包括其中的“有限使用”（Limited Use）要求。具体而言：

- Google 用户数据只用于提供你所设置的同步——读取并更新你的 Google Tasks，使之与所选的提醒事项列表一致——以及向你显示同步状态。
- 这些数据不会传输给任何人，除非是作为你所要求的同步的一部分写入你自己 Mac 上的“提醒事项”，或法律要求。
- 这些数据不会用于广告、用户画像，也不会用于训练人工智能或机器学习模型。
- 没有任何人会阅读这些数据。软件在你的 Mac 上运行，维护者无法访问。如果你选择把诊断信息或日志分享给别人，发送什么由你决定。

## 数据保留多久

本地数据会一直保留在你的 Mac 上，直到你删除它。卸载时选择删除数据（App 中的“卸载…”，或 `ltb uninstall --delete-data`）会删除设置文件夹和日志。删除本地数据不会删除你的提醒事项或 Google 任务；已同步的 Google 任务备注末尾的同步标记会一直保留，直到你自己删除。

## 你的选择与控制

- **撤销 Google 访问权限：** 随时可以在 <https://myaccount.google.com/permissions> 中操作（找到“Local Tasks Bridge”，或你自己客户端的名称），也可以运行 `ltb signout --revoke`。
- **撤销提醒事项访问权限：** 在“系统设置”→“隐私与安全性”→“提醒事项”中关闭。
- 随时可以在菜单栏中**暂停**同步、选择要同步的列表，或卸载 App。
- **一切都可以查看：** 软件是开源的，它的所有文件都在上面列出的位置。

## 安全

登录使用 Google 的 OAuth 流程，配合 PKCE 和回调到你自己 Mac（`127.0.0.1`）的重定向，并会校验每次登录的 state 参数。本地文件只对你的用户账号开放。没有任何存储或传输方式是绝对安全的；如发现安全问题，请按 [SECURITY.md](SECURITY.md#安全政策简体中文) 中的说明报告。

## 儿童

Local Tasks Bridge 是一款通用的效率工具，并非面向儿童，也不会为维护者收集任何人的数据。

## 变更与联系方式

如果软件处理数据的方式发生变化，本政策会在仓库和公开页面上更新，并注明新的生效日期，同时在[更新日志](CHANGELOG.md)中列出这项变更。

如有疑问：请在 <https://github.com/siyuanj/local-tasks-bridge/issues> 提交问题（请勿包含个人数据），或使用 Google 授权页面上显示的支持邮箱。
