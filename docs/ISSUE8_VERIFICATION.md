# Issue #8 部署交付验证

日期：2026-10-27。基点：`f7fb6c614d443478388a0e0d7d057ef7118c8670`。
本记录对应恢复后的 Issue #8 源码；最终提交 SHA、镜像包及当前 CI 结果在部署 PR 中补充。
原部署草稿及历史日志保留，未用旧结果替代下表的重新执行。

## 我跑过：提交前验证

| 环境 / 命令 | 退出码与结果 |
| --- | --- |
| Windows Node 22.23.3 / pnpm 9.0.0：`pnpm install --frozen-lockfile` | 0，依赖锁未修改 |
| Windows：`pnpm validate` | 0 |
| Windows：`pnpm test:portable` | 0，16 项脚本测试、41 项应用测试通过 |
| Python 3.12.10：`python .engineering-guard/test_guard.py` | 0，12 项通过；含真实 Git 钩子、暂存区和 CI 事件入口 |
| Python：`python -m unittest discover -s deploy/test -p '*_test.py' -v` | 0，30 项通过；归档、版本、恢复、资源、SSH、Caddy 边界 |
| 隔离 Linux Docker：`python deploy/test/receiver-integration.py --output <新证据目录>` | 0，真实 SSH forced-command → 接收器 → Docker 发布、坏包拒绝、启动失败恢复及回滚 |
| Linux 镜像：`python deploy/test/build-image.py --development --output <仓库外目录> --engine <固定引擎检出>` | 0；开发镜像不生成可发布包 |
| 镜像内部：冻结安装、`pnpm validate`、`pnpm test:portable` | 均 0；16 + 41 项通过 |
| 镜像内部：`pnpm test:ppt` | 0，49 项通过，跳过 0；包含真实 Python 和 Chrome |
| 镜像内部：`pnpm test:ppt:golden:geometry` | 0，12 页通过 |
| 镜像内部：`pnpm build`、`node deploy/test/build-smoke.mjs` | 均 0 |
| 镜像内部：`pnpm audit --json`、`pnpm audit --prod --json` | 均 0 |

镜像运行环境固定为 Node 22.23.3、pnpm 9.0.0、Python 3.12.14、
Chrome for Testing 152.0.7977.64、Playwright 1.64.0、Pillow 13.0.0；
下载摘要和字体版本见 `deploy/test/runtime-lock.json` 及 Dockerfile。
引擎候选为 `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`，未更新正式引擎锁。

SSH 集成使用本地隔离 Docker daemon 和微型应用夹具，不连接实际服务器。
前两次夹具运行遇到构建工具/镜像下载失败；保留失败日志，配置夹具使用本机
已有代理后重新完整执行通过，没有绕过接收器检查或修改服务器配置。

## 本轮红绿证据与小范围修复

Issue #8 未登记时新增合法流程测试失败；登记真实批准后通过。
在临时检查器副本中故意禁用生命周期判断时，新增拒绝断言失败；原检查器不变，
恢复后 12 项全部通过。既有测试继续证明：工作区修好但暂存区仍错误时拒绝提交，
错误 PR 关联、未批准 Issue、直接推送或删除 main/master 仍被拒绝。

复查实际生成路由发现：读取请求体前检查并发，读取后才占用名额；两个请求可
同时进入生成。真实 POST 路由回归在旧行为得到 `[502, 502]` 而失败，补上读取后
的同步检查后得到 `[429, 502]`，并验证失败后名额释放。无队列或响应结构变更。

该修复落实已经批准的单任务预算，Critic Loop 如下：

| 方案 | 成本 / 副作用 | 接受评分 |
| --- | --- | --- |
| 保留原检查 | 无改动，但并发请求可能超出单任务内存预算；已被真实入口复现 | 45/100，拒绝 |
| 读取后再次检查，再同步占位 | 一条检查，沿用既有 429 提示；不增加状态或接口 | 92/100，采用 |
| 新增队列或跨进程锁 | 需要取消、超时和持久化约定；超出单实例试跑需求 | 55/100，本轮不采用 |

原草稿中的 Cookie、归档、回滚等红绿记录保留；本轮在迁移源码上重新运行绿色
验证和真实 SSH 调用链。生产 Cookie 使用 Secure；开发 HTTP 保留现有调试行为。

## 日志摘要

完整日志保存在仓库外 `evidence-issue8-resume`；下列 SHA256 用于核对本次记录，
不包含密钥、服务器业务数据或私有错误台账。

| 日志 | SHA256 |
| --- | --- |
| guard-green.log | `b8a7fda82bcf4b458ed492a1489e8d6e3a9435d2c4e6f7b8fafa1672ce6f068a` |
| python-boundaries.log | `d4e76631199994e7f902db2b0bf18bb5f1ff66f59b654ed1a0ce823142b6a39c` |
| windows-validate.log | `15d950ff59a10f1cd52adb039d7fabf6e89bded99559c2ce043ef7f9d00ec60e` |
| windows-portable.log | `98e336dea57c0fa4b16f4392e03e6eeddfa005238170e2c4c523d05eaed13b64` |
| development-build-3.log | `77453a0f88432242f5c694b14d375f3b8c58dd22f72a48d0b618229277439c86` |
| capacity-race-red.log | `f1b19fb1a705bcae4ac7b11362b8bd0038f6e8c95fcf227b960054aa69566a86` |
| capacity-race-green.log | `30af3a3c448556fb259ed6964b916435d2536bd7e05037704255689a3ec660de` |
| receiver-linux-current-3.log | `a3765f4d39de5d7f484e16bd2b38752a73e3ec600f3c0834487227e29c23cf02` |

## 尚须区分的验收

提交前绿色检查不等于正式包已验证。提交干净源码后须重新构建绑定完整 SHA 的包，
在最终镜像验证网页、静态资源、Python、Chrome 和两次独立 12 页零差异捕获，
并在 PR 记录包摘要、内存峰值、OOM 计数及实际 CI 结果。

本地 1 核 / 1GiB 测试不构成服务器容量验收；不增加容器交换空间。
实际服务器的 DeepSeek、COS、手机预览/分享、原站可用性尚须所有者发布后验证。
Mac 原生复验、正式基线和最终引擎配对仍是独立门禁。本轮不合并、不部署。
