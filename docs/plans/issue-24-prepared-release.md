---
issue: https://github.com/damascenosteven-oss/YULING-mini-app/issues/24
status: accepted
base: a4cffd2bfccbb270c5defe0b8c782651b150f08c
adr: docs/adr/0011-prepared-release.md
---

# 手机准备完整包后单独发布

所有者于 2026-10-29 确认完整计划后明确要求执行。授权独立 Issue 工作树中的代码、测试、分支推送和审核 PR；合并、实际 prepare/publish/rollback 由所有者手机触发。

我跑过：发布 #10 的 403 个依赖离线安装、测试和生产构建成功，生产依赖审计因 npm TLS ECONNRESET 失败，未上传服务器。源码缓存还出现对象存在但 pinned 引用没有更新、克隆无法检出的边界。

## 已批准设计

- 手机工作流提供 prepare、publish、rollback，所有者与受保护 main 限制和串行队列保留。请求 schema 2，prepare 使用 ppt-test-local-prepare，发布/回滚沿用 ppt-test-local-relay；旧协议拒绝。
- prepare 获取固定源码、运行环境及依赖，正式镜像构建、全部测试、完整/生产审计和两次独立 12 页零差异全部成功后，将完整包及证据摘要原子接受到仓库外 prepared-releases。prepare 不连接服务器。
- 审计移出可缓存的 Docker 层，固定 Node/pnpm 读取同一提交锁文件。有效 JSON、退出 0、全部漏洞数为 0 才通过；仅网络故障、429/5xx 最多三次，每次 90 秒，间隔 2/5 秒。审计有效 24 小时；未来时间拒绝。
- 同 SHA 有效包校验复用；过期 prepare 只刷新两份审计，包、镜像和测试证据保持。损坏包拒绝刷新。
- publish 只使用当前 main 的有效包，不获取源码、不下载、不构建、不审计。包缺失/过期提示先准备。上传前和激活前复核请求、main、检查和取消；失败不自动重试。
- 保存最近两个已接受的本机版本；只在新版本接受且无占用后清理专用包目录内更旧版本，不删其他缓存、镜像、工作树。
- 完整 SHA、锁摘要、引擎/运行环境摘要、镜像身份、包摘要、测试证据及审计完成时间绑定。拒绝不完整目录、符号链接、错误版本。源码缓存命中也要在锁内固定可克隆引用。

## 验证和交付

红绿测试覆盖真实手机请求、电脑处理、缓存、审计、准备、发布、SSH 和状态入口。验证 prepare 不调用服务器、publish 不调用构建/下载/审计；npm/PyPI/Debian 不可达时有效包仍可发布。覆盖刷新、时间、损坏、并发、取消、旧协议及回滚。

运行工程门禁和完整发布检查；CI 对实际 PR head/main 构建正式包、验证 Python/Chrome、静态资源、两次 12 页零差异及受限 SSH 回滚，仅上传脱敏小证据。PR Closes #24，核对当前三项 CI。

不修改服务器接收端、Caddy、秘密、资源预算、引擎锁、Golden 或 Mac 基线。不触发真实 prepare/publish/rollback。合并后仅更新电脑接力并确认待命。
