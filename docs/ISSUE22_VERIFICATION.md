# Issue #22 离线依赖构建本地验证

`issue: 22`  `status: local-verified-with-gap`  `base: a957895ed46c0457a13b05a8d1ea104a64729e98`

本记录对应待审分支的开发验证镜像，镜像内 `source_dirty=true`，
`app_sha=7be25759329dbb4c604ae0039f7c8b7ac3d958e8`；不是可发布的正式包。
PR 当前提交的检查结果需要在 GitHub 单独核对。

## 我跑过

| 命令或检查 | 实际结果 |
| --- | --- |
| `build-image.py --development --prepare-only --runtime-offline --dependency-cache` | 退出 0；固定运行环境、引擎和依赖缓存准备成功 |
| `build-image.py --development --prepare-only --runtime-offline`，独立输出目录 | 退出 0；CI 使用的无持久缓存预取路径成功 |
| `build-image.py --development --runtime-offline --dependency-offline` | 退出 0；Docker 的 `RUN --network=none pnpm install --offline --frozen-lockfile` 复用锁定的 403 个依赖，`downloaded 0` |
| 镜像内 `validate`、portable、跨仓库、12 页 geometry、生产构建、完整与生产依赖审计 | 镜像构建退出 0；portable 脚本 16 项和单元 41 项通过，跨仓库 49 项通过，geometry 12 页通过；审计命令均退出 0 |
| WSL root：`python3 -m unittest discover -s deploy/test -p '*test.py'` | 退出 0；109 项通过，无跳过；包括缓存缺失、损坏、锁身份、符号链接、并发、超时、缺包及构建失败不上传的断言 |
| `verify-image.py --build-output` | 退出 0；两次独立 12 页捕获零差异，1 GiB 限制下 `oom=0`、`oom_kill=0` |
| 最终镜像内版本查询 | Node 22.23.3、pnpm 9.0.0、Python 3.12.14、Chrome for Testing 152.0.7977.64 |
| 受限 SSH 接收端集成测试，WSL + Docker Desktop | **未通过**；上传和归档校验成功，激活测试容器时 Docker Desktop 拒绝绑定 WSL 网关 `192.168.48.1:5000`，返回 `ports are not available`；未接触真实服务器 |

本地先让新增离线安装及禁网断言失败，再实施并重测通过。缺包模拟先证明
缓存不能被接受，然后增加清晰错误提示并重测通过。首次预热被额外的
`pnpm store status` 检查拒绝；改用缓存内容摘要加隔离冻结离线安装验证后通过。

日志 SHA-256（原始日志只保存在本机外部证据目录）：

| 日志 | SHA-256 |
| --- | --- |
| 依赖预热 | `73c1b9ab9f5c1cd517770bd207bad6460a58e9508e5092c177cbcad10dbe1b14` |
| 无持久缓存预取 | `73c1b9ab9f5c1cd517770bd207bad6460a58e9508e5092c177cbcad10dbe1b14` |
| 禁网镜像构建 | `ac831d8324aaf595aef09823908f531c2f6dfe36b1266bb801990bc7e7540a7b` |
| 部署单测 | `08e42e9b4631235a8c93c1175cf23ec63e13ed66b1abd180dc71a737299cd359` |
| 12 页镜像验证 | `654bb0e2ef34ff53bd315660cd455887dd2432bafecc67ec7ec0cc102d010ead` |
| 本地受限 SSH 集成测试失败诊断 | `90e0aa8fa04965328d4045488932f69ff9c7d4ddddb477214321e2187e9aa147` |

## 尚待核对

- GitHub Ubuntu Runner 上真实受限 SSH 入口、Docker 发布与回滚测试，以及当前提交的
  `engineering-guard`、`app-checks`、`release-checks`。本地 Docker Desktop 的
  网关端口限制不能冒充云端检查结果。
- 当前提交的干净生产包、手机新请求、服务器上传、网站与普通 PPT 生成均未执行。
- Windows 结果不构成原生 Mac 验收；Golden、正式引擎锁及 Mac 基线未变。
