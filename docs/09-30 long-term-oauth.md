# 长期 Google 授权准备（2026-09-30）

当前未完成长期授权：Audience 实测仍为 External / Testing，Publish app
禁用，提示必须先完成 Branding。应用名称已保存为 Local Tasks Bridge；
支持邮箱和开发者联系邮箱已有配置。应用首页、隐私政策、条款和授权域名为空。
尚不能断言其中哪一字段是当前控制台的具体阻塞原因。

## 官方要求与边界

- [Audience 官方说明](https://support.google.com/cloud/answer/15549945?hl=en)：
  请求 Tasks 等非纯身份权限的 Testing 授权及刷新令牌在授权后七天过期。
- [个人使用例外](https://support.google.com/cloud/answer/13464323?hl=en)：
  少于 100 人的个人使用可不提交完整验证；这不等于跳过控制台配置。
- [Branding 官方说明](https://support.google.com/cloud/answer/15549049?hl=en)：
  外部生产应用需配置应用链接，首页应属于本人控制的已验证域名。
- Production 消除上述测试模式的七天限制，但不保证令牌永久有效：撤销、
  安全事件及其他 Google 生命周期规则仍可使其失效。

只沿用本人项目 reminders-tasks-local-bridge 和现有 Desktop 客户端。
权限保持 Google Tasks + openid / email，不增加 Calendar 或 Cloud Platform。
Google Tasks 授权覆盖整个账号的 Tasks，My Tasks 限制属于本地代码。

## 下一步执行与验收

1. 用户解锁 Mac 后，检查 Branding / Verification Center 的具体未完成项。
   已知 Publish 按钮禁用，不通过脚本绕过控制台。
2. 如果确需说明网页，先准备真实的首页和隐私政策草稿，再发布到本人控制的
   站点。已通过只读 GitHub API 确认 siyuanj.github.io 公共仓库和 Pages 存在；
   本次没有修改该网站或上传任何内容。
3. 在最终扩展授权有效期前，按电脑操作接口要求取得具体确认，说明
   External / Production 允许其他 Google 账号对自己的数据授权，并不公开
   当前账号的待办或凭据。不要把改名保存当作 Production 已启用。
4. 临时停止现有 LaunchAgent，把原 token.json 备份到私有目录，保留 0600。
   通过现有 auth 流程，在 Production 下重新授权，使用 loopback + PKCE +
   state 校验，不显示回调 code、客户端 secret 或 token。
5. 核验实际 scope、refresh token 存在及新授权结果；执行一次官方刷新和
   只读 Tasks API 验证。不要从普通 access token 的一小时期限推断刷新期限。
6. 恢复 LaunchAgent，核验真实定时轮次和权限错误状态；保留 My Tasks 边界、
   单次破坏性限额 1 和待确认的 10 条完成计划。

完成标准是控制台 In production、新授权与刷新可用、后台实际轮次通过。
不能仅凭按钮点击或令牌文件存在报告长期授权完成。

## 当前阻塞

2026-09-30 23:30 CST：电脑接口返回 Mac 已锁屏，无法自动解锁。
已请求用户手动解锁；没有停止后台服务、替换令牌或改变 OAuth 发布状态。
