---
issue: https://github.com/damascenosteven-oss/YULING-mini-app/issues/22
status: accepted
base: a957895ed46c0457a13b05a8d1ea104a64729e98
adr: docs/adr/0010-pnpm-offline-release-cache.md
---

# 手机发布的锁定依赖预取与离线安装

所有者于 2026-10-29 明确要求实施已批准的完整计划。授权本 Issue 的代码、测试、分支推送及审核 PR；合并和手机手动发布由所有者操作。

我跑过：手机发布 #9 命中应用、引擎及固定运行环境缓存后，在 Docker `pnpm install --frozen-lockfile` 下载 `@aws-sdk/nested-clients` 时发生 `ECONNRESET`。发布未进入受限 SSH 上传，接收端无当前版、上一版或待发布版。问题是依赖安装仍然在线；网络中断的具体链路根因未证实。

## 实施

- 用已校验的 Node 22.23.3 和 pnpm 9.0.0，按应用清单、锁文件、运行环境锁及 Linux 架构识别仓库外依赖缓存。预取最多三次，每次五分钟，间隔 2 秒和 5 秒；完整性检查及隔离冻结离线安装通过后才接受缓存。缺失、损坏、符号链接、并发冲突或版本变化均失败。
- 电脑 `--warm-cache` 预热依赖；发布只读已接受缓存。CI 在隔离目录在线预取后执行相同的 Docker 离线安装。构建上下文仅传入依赖缓存，镜像内 `pnpm install --offline --frozen-lockfile`，并阻止安装脚本联网；不存在在线回退。
- 保留完整和生产依赖审计的联网且失败阻断行为。保留 GitHub 主分支、Checks、请求时效与重复请求核对；构建失败会标记 Deployment 失败，不调用上传或激活。

## 验证与交付

按红绿测试验证错误缓存、缺包、错误锁、超时、并发和在线回退被拒。运行工程门禁、冻结安装、validate、portable、跨仓库测试、geometry、生产构建、完整与生产审计、秘密扫描和最终镜像两次独立 12 页零像素差异。记录命令、版本、退出码、跳过项和日志哈希。PR 正文关联 `Closes #22`，核对当前提交的三个真实 CI 检查。

所有者合并后，代理只在电脑预热新 main 并确认接力等待；新的发布由所有者手机触发。#9 不重跑；不改服务器、应用 API、Golden、正式引擎锁、Mac 基线或视觉阈值。
