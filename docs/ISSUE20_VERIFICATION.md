# Issue #20 本地验证记录

`issue: 20`  `status: local-verified`  `base: 0513e22ea68ea5ab9f742b06796823c5513ae242`

本记录对应 `issue/20-runtime-cache` 的待提交实现。本机镜像构建使用开发验证模式，
镜像内 `app_sha=d9794495490026d26ca86b5e4a3de5aa6686030e`、
`source_dirty=true`；它不是可发布的正式包。PR 的当前提交和 CI 结果需另行核对。

## 我跑过

| 检查 | 实际结果 |
| --- | --- |
| `pnpm install --frozen-lockfile` | 退出 0 |
| `pnpm validate` | 退出 0 |
| `pnpm test:portable` | 退出 0；脚本 16 项、PPT 单元 41 项通过 |
| `pnpm test:ppt`，显式指定引擎、Python、Chrome 路径 | 退出 0；49 项通过 |
| `pnpm test:ppt:golden:geometry` | 退出 0；12 页通过 |
| `pnpm build` | 退出 0 |
| `pnpm audit --json`、`pnpm audit --prod --json` | 各退出 0；各级漏洞均为 0 |
| `python -m unittest discover -s deploy/test -p '*test.py' -q` | Windows 退出 0；101 项通过、8 项跳过 |
| WSL Ubuntu 24.04 定向缓存／接力测试 | 退出 0；27 项通过，含符号链接和真实并发断言 |
| WSL Ubuntu 24.04 以 root 执行完整部署测试 | 退出 0；101 项通过，无跳过 |
| 固定运行环境文件 SHA-256 与 `runtime-lock.json` 比对 | Node、Chrome、pnpm 三项一致 |
| `build-image.py --development --runtime-cache --runtime-seed-dir` | 退出 0；固定镜像构建通过，未生成发布包 |
| `verify-image.py --build-output` | 退出 0；两次独立 12 页捕获零差异，镜像内内存上限 1 GiB 下无 OOM 记录 |

本机直接运行的 Node 为 `v24.21.0`、pnpm `9.0.0`、Python `3.12.10`；
Docker 为 `29.8.0`。镜像按 `runtime-lock.json` 使用固定 Node `22.23.3`、
Chrome `152.0.7977.64`、Python `3.12.14`、pnpm `9.0.0`、
引擎 `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`。

## 待验证

- 此处没有通过真实手机发布请求上传服务器，也没有验证 GitHub Deployment 写入权限。
- 外部 DeepSeek、COS 和正式网站验收未在镜像检查中执行。
- Windows 结果不构成原生 Mac 验收；Mac 基线和正式引擎锁没有变化。
- PR 创建后须核对当前提交的 `engineering-guard`、`app-checks` 和 `release-checks`。
