---
issue: https://github.com/damascenosteven-oss/YULING-mini-app/issues/30
status: accepted
base: 8e4d67ef7df721dbaf2010c283b4f864f7c310a3
adr: docs/adr/0013-admin-model-settings.md
---

# 简化生成与管理员模型设置

所有者于 2026-10-30 在本对话明确批准并要求实施完整计划，授权代码、测试、Issue 分支推送和审核 PR；不授权合并、部署、服务器操作或付费生成。

## 已核实与选择

我跑过：requiresResearch 对“目前宁波就业市场”返回 true；generateOutline 先调用 researchPrompt，未配置 BOCHA_API_KEY 时在模型请求前被拦截。main 受三个必需检查保护，本地基点与远端一致；现有共享邀请码不能识别管理员，容器尚无模型配置持久目录。

所有者选择管理员独立密码、全站一个模型配置；默认 DeepSeek，也支持公网 HTTPS OpenAI 兼容 Chat Completions、Bearer 和 JSON。仅环境变量 60/100、浏览器密钥 35/100、管理员/服务器持久配置 92/100，采用后者。成本与恢复见 ADR 0013。

## 已批准行为与接口

- 普通生成不再自动搜索，保留旧作品来源；明确未联网，模型数值为演示数据，不伪造已核验来源。COS 继续承担既有作品存储、历史及分享。
- 工作台入口、手机设置页；普通登录后单独管理员登录。字段为类型、Base URL、模型、密钥和 max_tokens/max_completion_tokens 参数；DeepSeek 默认 deepseek-flash/max_tokens，普通兼容接口不携带专用 thinking 参数。
- 管理会话一小时、独立签名、生产 Secure/HttpOnly/SameSite Strict；密码使用哈希且无默认值、不复用邀请码。密码重设撤销管理会话；应用退出同时注销管理会话。登录限流、写入同源检查、生产 Origin 明确配置。
- /api/ppt/admin/session 提供登录/状态/退出；/api/ppt/admin/model-settings 提供脱敏 GET、保存 PUT 和恢复环境默认 DELETE；其 /test 提供一次最多 20 秒的小型 JSON 测试，不保存、不生成 PPT。保存只进行本地校验，不额外付费请求。
- 镜像外目录 0700、文件 0600，仅运行账户访问；密钥使用会话秘密派生独立 AES-GCM 密钥保存。环境默认仅在无保存文件时生效，损坏时明确拒绝，不隐式回退。
- 原子串行写入和修订号冲突检查；留空密钥仅在服务类型/地址不变时保留，换地址须重新填写；每次生成的两次尝试使用同一配置快照，下一请求立即应用新配置。
- 生产连接仅 HTTPS，无 URL 凭据/查询/重定向，DNS 公网验证并固定连接地址，拒绝回环、内网、保留地址、元数据及 IPv6 绕过，保留 TLS 验证。测试和生成共用同一实现。
- 补初始化和部署代码：管理员遮蔽输入/哈希、目录挂载、正式读写/候选只读、新客户端传包前检查接收能力；不覆盖既有秘密，不把配置打入产物。
- 结构、技能、页数和引用保护不退化；现有 45/90 秒、8192/12000 token 上限和最多两次尝试保留。

## 验证、证据与交付

按 RED/GREEN 和故意错误验证权限、密钥脱敏/地址更换、持久化、损坏/并发/写入失败、URL 和 DNS/IPv6/重定向防护、兼容参数及上游/超时/JSON 错误。真实 HTTP 登录→管理员设置/测试→普通十页大纲→Python HTML/预览，外部模型/存储模拟，搜索为零，最多两次模型调用。

运行冻结安装、validate、portable、跨仓库、geometry、生产构建、两份审计、秘密扫描、工程门禁与部署回归；最终镜像在一核/1GiB限制下检查权限、真实 Python/Chrome 与两次独立十二页零像素差异。不冒充云端或真实业务验收。

通过原始钩子推送本 Issue 分支，PR 使用 Closes #30，报告三项当前 SHA CI。证据位于仓库外 G 盘。所有者合并后另行安排初始化、升级、部署和真实生成；本次不动服务器/Caddy/预算/正式引擎锁/Golden/既有作品/G 盘备份。
