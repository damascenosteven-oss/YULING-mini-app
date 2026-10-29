# Issue #26：严格权限镜像与错误报告验证

## 证据范围

我跑过：旧镜像 `32d6e72a80bf-40894523079-1` 被运行权限探针拒绝，退出 1。
最终配方的本机完整流程绑定干净提交 `556c7b30d81af51660974f2eb97537c385ce3085`。
其后仅补充手机中文错误摘要、相应单元测试和本报告；最终交付提交由 PR 的三项 CI 再次验证，不能用本机旧 SHA 冒充新提交结果。

本机端到端测试使用**模拟 GitHub API**、真实 Git 缓存检出、真实构建、真实最终镜像和封包接受入口。
没有创建真实手机请求；服务器调用和读取部署凭据被断言禁止。测试状态及证据在独立目录，未放入实际接力发布状态。

## 我跑过的命令与结果

| 命令/入口 | 退出码 | 实际结果 |
| --- | --- | --- |
| Linux root `python3 -m unittest discover -s deploy/test -p '*_test.py'` | 0 | 124 项通过，无跳过 |
| `python -m unittest discover -s .engineering-guard -p test_guard.py` | 0 | 20 项，实际 Git hooks/CI 事件及暂存区错误拒绝 |
| `python3 deploy/test/strict-prepare-check.py --output <新外部目录> --seed-state <既有缓存目录>` | 0 | umask 077，源码文件 0600；真实 prepare handler → 构建 → 验证 → 接受，服务器调用 0 |
| Docker 内冻结离线安装、`pnpm validate` | 0 | 固定锁文件和工具链 |
| Docker 内 `pnpm test:portable` | 0 | 16 项脚本、41 项单元测试 |
| Docker 内 `pnpm test:ppt` | 0 | 49 项跨仓库测试，无跳过 |
| Docker 内 `pnpm test:ppt:golden:geometry`、`pnpm build` 和构建冒烟 | 0 | 12 页布局、生产构建及静态资源通过 |
| 固定 Node/pnpm 新鲜 full/prod 审计 | 0 | 两份审计所有严重等级均为 0 |
| 最终镜像权限、网页/静态资源、Python/Chrome、quick 和 repeat | 0 | UID/GID 10001；28614 文件读取/写入边界；两次独立 12 页零差异；source_dirty=false |
| 故意派生不可读运行环境锁的镜像 | 5（预期拒绝） | runtime_permissions / image_permission_denied，无 verification 成功凭证 |
| 旧诊断、禁用错误分类、禁用手机错误映射三个隔离故障副本 | 各 1（预期拒绝） | 测试能发现回归，正常源码测试恢复通过 |

Docker 29.8.0；固定运行环境版本仍由原 runtime-lock.json 控制，文件未改。
镜像在 1 核/1GiB/无额外交换空间预算验证：`memory.peak=1073741824`，`max=95669`，`oom=0`、`oom_kill=0`。
**内存峰值触及上限，存在回收压力；不能据此声称服务器容量有余量。** 未改变批准的预算。

## 失败、停止和未验收项

- Windows 全量部署单元测试：123 项运行，7 failures、3 errors、9 skipped；本机 C 盘可用空间低于部署测试所需 8GiB，另有 Linux 平台测试限制。没有改门禁适配这个环境；目标 Linux 全量结果如上。
- 初始配方在最终镜像追加递归权限层；为避免重复应用层，明确停止该轮本机测试，随后改为最终复制前规范权限并重新完整运行。中止日志不算通过证据。
- 本次不改变应用 API、引擎锁、Golden 图片、服务器、Caddy、电脑凭据或 umask；不作 Mac 验收。
- 真正手机 prepare、publish、普通 PPT 生成和服务器容量验收仍由所有者后续执行。
- PR 创建时 CI 尚未运行；交付以当前 PR head 的 engineering-guard、app-checks、release-checks 为准。

## 哈希与产物

- 本机正式包：982200320 字节；SHA256 `5743ba3b9424918bb6c2f0be09801390defd1305b69f8bc6da148e8b19d9f3d1`。
- 完整严格权限流程日志：`6edf7b41b7e8428cb7d99002f2b3229f13fb98c787305504c4485d10f8196fee`。
- Linux 最终单元日志：`5f53a6775e150a34278343b1ff5a9c455abdca45b6622bfdbf625e62741000e0`。
- 故意错误证明：`6b120c5a1f48ba5e17a05d7650d88f13e51953b2548f7a36f9d590f30500dbf8`。
- 严格流程 result.json：`0fb5f52e25e7ca97dd0fbfbc16453943584b60e677930698dc2a632076e81ebb`。

仅本次故障派生镜像及随机诊断容器被清理。既有项目、源码工作树、分支、镜像和实际接力请求记录均保留。
