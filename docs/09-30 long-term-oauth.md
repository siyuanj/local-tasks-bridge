# 长期 Google 授权（2026-10-01 完成）

Google Auth Platform 已实测为 External / In production。应用名称是
Local Tasks Bridge；应用首页、隐私政策和授权域名均已保存，公开页面由本人
`siyuanj.github.io` 托管。新授权令牌已签发、独立刷新并访问 Tasks API；后台
三轮定时执行通过。

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

## 实际执行与验收

1. 发布本人控制的应用首页和隐私政策，GitHub Pages 构建成功并实际读取两页。
2. Google Branding 保存两个 URL 和授权域名；Audience 确认 In production。
3. 停止 LaunchAgent，把旧 Testing token 私密备份后，通过 loopback + PKCE +
   state 校验重新授权。scope 集合保持 Tasks + openid / email；未增加 Calendar、
   Drive、Gmail 或 Cloud Platform。
4. 新 refresh token 与旧 token 不同，独立强制刷新成功，Tasks API 检查通过。
   Google 未返回 `refresh_token_expires_in`；这说明没有测试模式的七天字段，
   不能据此声称令牌永不失效。
5. 令牌轮换触发账号绑定保护。使用新旧 access token 分别查询官方 userinfo，
   确认 subject 指纹和邮箱相同，且旧状态确实绑定旧 token；私密备份状态后只
   更新 Google 绑定哈希，12 条 task 映射保持不变。安全 dry-run 通过。
6. 系统代理偶发 TLS EOF，后台 GET 原先没有重试。LaunchAgent 明确沿用当前
   本地系统代理；引擎只为幂等 GET 增加三次有限重试，写请求不重试。97 项测试、
   Python 编译、shell 语法和 release gate 均通过。运行版本为 `4375a1d`。
7. 后台于 08:23:05、08:24:33、08:25:53 CST 连续成功，失败计数为 0；
   状态回到 `awaiting_mutation_approval`，仍仅暂缓既有 10 条完成操作。

长期授权的本次验收已完成。尚未执行整机注销/重启验收；用户撤销、Google
安全事件或其他生命周期规则仍可使 refresh token 失效。旧 token、状态和
LaunchAgent 备份保存在私有 OAuth 备份目录，不纳入 Git。
