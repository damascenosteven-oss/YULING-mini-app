# Issue #12 提交前验证记录

基点：`f892eae73d2464f0fb456da9f15a7426bcf2ac68`。本报告记录工作树验证，
最终提交、绑定提交的镜像验证及真实 PR CI 以 PR 正文交付回执为准。
没有操作真实服务器、合并或触发发布；不宣称已修复真实网络中的传输耗时。

## 我跑过

| 检查 | 实际结果 |
| --- | --- |
| `python -m unittest discover -s deploy/test -p '*_test.py' -v`，Linux root 隔离容器 | 52 项通过，退出 0；覆盖接收预算、客户端子进程、升级/恢复、旧版拒绝、归档和版本校验 |
| `.engineering-guard/test_guard.py -v` | 13 项通过，退出 0；真实 Git 钩子和源绑定 CI 结构 |
| 目标 worktree 实际 pre-commit | 故意错误暂存 Plan 被拒绝；正确工作文件无法掩盖；恢复后退出 0 |
| 故意关闭预算、旧哈希检查、artifact ID 检查 | 三个隔离突变分别被测试拒绝，退出 1；未修改已安装门禁 |
| `receiver-integration.py` 实际客户端 → SSH 强制命令 → receiver → Docker | Linux 隔离环境退出 0：持续慢传、空闲/总/整理超时、截断、坏摘要、两次发布、启动失败恢复、回滚、任意命令限制；升级 CLI、重复升级和版本握手通过 |
| `build-image.py --development` | 退出 0：冻结安装、validate、portable（16 脚本 + 41 单元）、跨仓库 49 项且零跳过、12 页 geometry、生产构建、完整及生产依赖 audit |
| `verify-image.py`，1 CPU/1GiB 且不额外使用 swap | 退出 0；静态资源、真实 Python/Chrome、两次独立 12 页捕获均零差异；已打开抽样页面检查 |
| gitleaks 工作树扫描 | 退出 0，无泄露发现 |
| 官方 `download-artifact@v8` 函数、本地服务替身 | 首次、仅重跑 release、全量重跑、过期 ID 不回退最新、摘要不符共 5 场景通过；空/非法 ID 由仓库 CLI 测试覆盖 |

镜像固定环境：Node 22.23.3、pnpm 9.0.0、Python 3.12.14、Chrome 152.0.7977.64、
Playwright 1.64.0、Pillow 13.0.0；引擎 `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`。
宿主测试调度为 Windows Python 3.12.10；部署单元与权限/锁测试运行在 Linux Python 3.12。
官方动作函数模拟使用 Node 24.21.0 的隔离模块加载，不是应用工具链或真实 GitHub 重跑。

## 实测限制及失败记录

- Windows 检出的测试 shell 脚本带 CRLF，Linux 无法执行；本地改用与 Git blob 一致的 LF。
  未更改脚本 Git 内容。Docker Desktop 不支持测试所需的网关地址绑定；没有放宽绑定规则。
- Linux 隔离 Docker 初次拉取固定镜像遇到网络/TLS 错误。成功测试使用预先构建的同源码测试主机，
  比对接收器完整 SHA256；固定 Node 镜像 digest 核对后离线导入。只复用测试镜像构建缓存，
  真实受限 SSH、接收器、Docker 发布和恢复逻辑全部执行。
- 开发镜像的标签明确为 dirty，仅用于提交前验证，不能发布。
- 镜像内存峰值 1073741824 字节，`oom=0`、`oom_kill=0`，但曾触及内存上限；
  不代表真实服务器容量验收通过，不调整资源预算。
- 没有触发真实 GitHub 重跑或等待真实产物过期；官方动作服务替身仅为本地模拟。
  [v8 动作源码](https://github.com/actions/download-artifact/blob/v8/src/download-artifact.ts)
  按固定 ID 过滤，找不到即失败，摘要不符默认失败；用户新运行后仍需实际验证。
- 新的 45/2/15/65/90 分钟预算是设计边界，不是实际网络吞吐保证。Mac 验收、
  真实 DeepSeek/COS、手机业务与服务器容量仍未验收。正式引擎锁和 Golden 不变。

## 关键源码 SHA256（Git LF 形式）

| 文件 | SHA256 |
| --- | --- |
| `deploy/test/release.py` | `d4526feed16f92b0131be01f12501a1deb1b74017a48f1ed0d0a5aad26174a9b` |
| `deploy/test/bootstrap.py` | `54664eb07cd6445c53a553884350d548f4dcf37a0cf00ac86a1a3cd9704f165b` |
| `deploy/test/ssh-client.py` | `e75f391e18b65c4fa46c0c6cdfed2f4908de41d8626e51410e12482c16208cae` |
| `.github/workflows/test-site.yml` | `2d4bda03d58316b47360dd266442a3f2ef2e5aca67661df5ecc5aab037565aae` |

## 本地日志 SHA256

日志保存在任务外部证据目录 `evidence-release-timeout`，不包含真实凭据或应用配置内容。
故意错误日志的非零结果是预期拒绝；其他检查的通过退出码见上表。

| 日志 | SHA256 |
| --- | --- |
| `deployment-unit-final.log` | `293894e26adc6a6efc58f766e7110e360f6f94307c291a21fb552025ff73372b` |
| `guard-tests.log` | `b24ecb585c570457fdc746994614db27e9ac4656a44c0ae4d48c4d03a5b05946` |
| `actual-precommit-red.log` | `ae3175093164d4789edfd89becf885b0a3923e95051f2bc3e9006b1c2665fe87` |
| `actual-precommit-restored.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `mutation-budgets.log` | `4329b85f492f695522092abf90a43c8687acad6dcb7f414551c0a6a14c19f6fa` |
| `mutation-old-hash.log` | `1e4e3f28bcb08b07f3fe3beb4fc09252e4d4e94b7c59e2d1edf6cc27264d3e37` |
| `mutation-artifact.log` | `6b7a488946a5444c76eb8e98afd7ff09d900830a9e2a5b0f8b1eb9d5a92715e1` |
| `receiver-offline.log` | `df89fde02a145aa140190c51ea442fcf4e389dad05679847c5f23fc4397e6d0d` |
| `offline-orchestration.log` | `78fea6ce5604c7dfaa4e7250e26377f20e22e4da8dfd0cf91cf22287423ca4ef` |
| `artifact-action-simulation.log` | `8cc8e2c3207543f7fa938aa464b49c83997cb4a462a6ed40150e7408fc09333a` |
| `development-image-build-2.log` | `08b97ea7220394dcc2913b37940ec792c0c092de9d1d8ba22b0843e5fe3ed7d4` |
| `development-image-verify.log` | `4f33f7ca700868caec4daaba34f24208a9ce7faa137a9a8163421a8519787f23` |
| `secrets-working.log` | `b4e9e4416651d6f0456bd4c86eda40c68d6a9334b7184a0fb0eff7ddb05a24b9` |
