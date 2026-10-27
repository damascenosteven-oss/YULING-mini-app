# Issue #14 测速实现验证

本报告记录本机测试；真实三段云端测速由所有者合并、配置专用权限、升级接收器后手动运行。
手机操作见 [PHONE_NETWORK_PROBE.md](PHONE_NETWORK_PROBE.md)。本轮没有操作生产服务器或触发发布。

## 源码与环境

基点 `6af7c8e9361ceffcad1510cd1a83e4feb29a922f`；测试对象为 Issue #14 worktree 的迁入后源码，
不是把历史基点的结果当成本次结果。最终提交以本 PR 当前 head 的 CI 为准。
应用、依赖锁、正式引擎锁和 Golden PNG 与基点一致；引擎仍为 `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`。
Windows 应用测试使用 Node 22.23.3、pnpm 9.0.0、Python 3.12.10、Pillow 13.0.0 和 Chrome 152。
测速 SDK 在独立 Linux Python 3.12 环境完成哈希固定安装；不进入应用依赖或镜像。

## 我跑过

| 命令／检查 | 实际结果 |
|---|---|
| `pnpm install --frozen-lockfile` | 退出 0 |
| `pnpm validate` | 退出 0 |
| `pnpm test:portable` | 16 脚本测试、41 单元测试通过 |
| `pnpm test:ppt` | 49 项通过 |
| `pnpm test:ppt:golden:geometry` | 12 页通过 |
| `pnpm build` | 退出 0 |
| `pnpm audit --json`、`pnpm audit --prod --json` | 均退出 0，未报已知漏洞 |
| Linux `python -m unittest discover -s deploy/test -p '*_test.py' -v` | 70 项通过，无跳过 |
| `python .engineering-guard/test_guard.py` | 14 项通过，含 Issue #14 暂存区错误及错误 PR 关联拒绝 |
| 哈希固定安装后 `python deploy/test/probe-sdk-check.py` | 官方 SDK PUT/GET/DELETE 签名验证通过，无云请求 |
| 测速及构建工具的 `pip-audit` | 13 个固定依赖未报已知漏洞 |

红绿证据包括初始缺失测速实现、SIGTERM 清理入口、下载请求正文 EOF 在计时范围内的失败与修复。
客户端等待上限另经真实子进程红绿测试，保留最后进度并作为失败样本继续独立链路。
另在隔离源码副本故意破坏大小、摘要、pending、域名、空闲时限、总时限、失败样本统计和未验证 COS 统计；
8 项故障均被测试拒绝。没有修改正式门禁检查器或关闭钩子。

SDK 的签名起始时间会向前预留 60 秒；校验固定时间下的起点和生成后 600 秒的终点，
没有把起止差误报为实际剩余有效期。初始错误断言已修正并重跑通过。

## 真实调用入口与模拟边界

本地隔离 Docker daemon 中运行实际客户端 → SSH forced command → 接收器：
校验完整上传、截断、超量、坏摘要、固定边界、缩短测试时限下的停滞/总超时、锁冲突、清理和版本状态不变。
本地 TLS COS 模拟器保留固定主机名及证书验证，覆盖 PUT/GET/DELETE、拒绝重定向、403、坏摘要。
这些是实际网络/SSH 调用，但 **不是腾讯云 COS 或目标服务器的测速结果**。
旧发布流程的归档拒绝、发布、启动失败恢复、回滚和 forced-command 防逃逸仍执行。

本地环境使用已缓存且核对摘要的夹具镜像，临时脚本仅适配夹具获取方式；测试中的客户端和接收器来自当前源码。
远端 `release-checks` 使用仓库原有入口自行构建夹具，并保留最终应用镜像及两次独立 12 页捕获检查。

## 尚未验证与交付边界

提交本报告时远端当前提交的三项 CI 尚待运行，不以本地通过代替 CI。
真实 COS 权限、同地域实际路由、云端首次测量、服务器升级和大包发布能力均未验证。
强制终止可能留下本次对象；报告保留对象名，所有者按精确对象清理，不清空桶。
小文件筛选达标也只建议下一轮大文件测试，不自动调整发布方案。

## 本地日志摘要

日志保存在本次独立证据目录；以下 SHA-256 便于核对，日志未包含生产凭据。

| 日志 | SHA-256 |
|---|---|
| unit-linux-final.log | 787ee696ddde48916ce6833fe8e83d5d85b40a3fbc1e09646a9e23f29eb8ee85 |
| guard.log | 42ad4851b95d928bf17d1c9c72ced330b17cf42927a4da8fa8016f1d6d9c993e |
| sdk-ci-green.log | 22e3b429b4e8d943a757768ab6bfd9eb61d5e55fb996bfaa94eb4441cc30a0e4 |
| sdk-audit.log | b7f6bba5e864a406f41483d3d8639efe28b14b28237828b798c83a7568f3289f |
| mutation-receipt.json | 1648113defc636f576618bbfff388f3749f9d059bead630eb7e92051eefd8304 |
| install.log | 54afe96525db6e6c73ac87beef9b913a812e7cfa4d01208ef568f0b8a2684c76 |
| validate.log | 78573100a9a9c255544f7f3fe8d5086dd3180d7f94de62ba89fcd3db73f99fc5 |
| portable.log | 09f276de032a3254ee98fad628f90d9ae0146604c750c4e2682847386141d290 |
| integration.log | 94a2ea552fa4107cdd4434fa6f3d78b5f5cfc05a8f8584b51f0eda1c4361b21a |
| geometry.log | 3b25521ef09662757a7cb61ef2b85765c8be2866c74af649affa79f1144febd9 |
| build.log | 7f9b683a72ba700ecb43ffe60a23f4feaa67ba06b857a883848e3e15799ced48 |
| audit-full.log | 6cadcf2e93ca634e41afe74f167d3a4f653bef848f631edcb2b577d84b5870b9 |
| audit-production.log | 36872159045ec6e4454410c8f52e9219e00a49a67cc78a3a520e3a3744ac15bf |
| receiver-offline.log | a16f29b8693d803d8f4687b665199145d6b72a34cba9e4ab8a030976f69cd7b2 |
| offline-source.json | 2dc8f390dc80826c81d9941fcb8a39a8cafbcc305cdcfc09cbbbd8e6a9407482 |
| secrets-final.log | 6baa8b44cbbfdc6febd0ee6010123bd5dd094a9663ed2df485b794f5c70ace9b |
| staged-source.json | bcbb11a44d1efa3ebb3932eeb7d09332a97bd65f9edec0394697e6ffbc5ff43e |
| agent-entry.json | e3566b3a06430868d71e9287dfd6c6c520a3da027aabea01951d407ee131dc2f |
| client-timeout-red.log | 7fc0b74ac3b087c0d31e584ad030da91f0f463b072b45880b3c26099f18987b3 |
| unit-linux-timeout-final.log | a8594e70cbaa4cebed62d281725d63b130dceb92275a8b2450a62f3281737734 |
