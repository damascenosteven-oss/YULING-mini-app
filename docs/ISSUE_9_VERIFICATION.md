# Issue 9 门禁接入验证记录

源码基点：`c8bf02a0d008bf3140787fa1947504f75b731870`。
环境：Windows、Python 3.12.10；最终 Git 提交和远端 CI 以交付 PR 的当前提交为准。
本文件记录提交前本机证据，不将尚未运行的远端检查写为成功。

## 我跑过

| 检查 | 实际结果 |
| --- | --- |
| 临时检查器故意取消生命周期及主分支拒绝 | 7 个测试产生 8 条预期断言失败，0 个运行错误；实际安装版本未修改 |
| `python .engineering-guard/test_guard.py -v` | 10 项通过；覆盖实际安装钩子、真实提交、pre-push 标准输入、PR 事件和 Codex 适配器 |
| 正式 `install` | 成功登记 Git common-dir，备份路径已保留；原自定义钩子为零，未修改全局适配器 |
| 目标工作树 `git hook run pre-commit`，暂存 proposed Plan、工作文件 accepted | 退出 2，Issue/accepted plan/base mismatch |
| 相同故障通过实际 Codex `git -C … commit --dry-run` | PreToolUse 在执行前拒绝，未产生提交 |
| 恢复暂存区后，实际钩子及 Codex dry-run | 均退出 0 |
| 目标 `git hook run --to-stdin=… pre-push`，本地 main 引用输入 | 退出 2，拒绝 Direct push/delete；未向远端 main 发出推送 |
| `docker run --rm -i zricethezav/gitleaks:v8.28.0 stdin --redact --no-banner` | 扫描本次全部暂存文件内容，退出 0 |
| 暂存快照与安装检查器逐字节比较、Plan/ADR SHA256 比较 | 相同；读取 Git 暂存 blob，不以未暂存修复替代 |

首次测试运行的两个错误来自测试驱动调用独立 sh 而本机 PATH 没有该命令；
改为 Git 自身运行 pre-push 后通过。一次故障注入检测暴露测试断言直接访问缺失
字段，已增加明确的拒绝断言；重跑得到预期红、恢复绿。共享检查器逻辑没有改动。

## 日志完整性

原始日志保留在工作树外，包含本机临时路径，不提交私有目录或其他项目记录。

| 日志 | SHA256 |
| --- | --- |
| deliberate-fault.log | `681d4bc62fd44f3aa1cfbce2d722816b789e394ab16175544b4b8d90a5d2bf56` |
| guard-tests.log | `f6005af5e6ce89f4291734e0016b907f545dc6b9ee1bcdb6a936814c29a00842` |
| target-red.json | `7bcd2b721d752bf0a9d15758b430f20bd600729f929bde6ca7a3bb30d1488f4b` |
| target-recovered.json | `753a32c25cf6b1dbe3a1a74ef5f4bfd1cc43f4c6786034fa720ea1cf3ff471de` |
| sensitive-scan.log | `15a59ea1dfd5853704f9f4086afe3a9b9deb5f334dd69e002ca3342775c62d72` |

检查器版本 1.0.0，SHA256
`502ebbbac181494153662d7b08056f8a303a7039af80e18106c1f214c42f5a29`。
策略文件内固定 Plan/ADR 哈希，Git 提交绑定其余源码；外部交付清单记录全部文件哈希。

## 待远端完成与明确边界

推送后检查 `engineering-guard` 及既有 `app-checks` 当前 head 的真实结果，报告在 PR。
本机未重复运行产品冻结安装、跨仓库 Golden 和发布镜像测试：本次没有产品、
依赖、Golden、引擎锁或部署改动；既有 app-checks 将运行 validate、portable、build。
目标仓库 GitHub main 保护尚需所有者设置，步骤见 ENGINEERING_GUARD.md。
CI 文件本身不能证明远端强制保护，亦不证明 Mac 验收或服务器容量。
Issue #8 的 33 个未提交/未跟踪文件已在仓库外记录哈希，用于交付前核对未改动。
