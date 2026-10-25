---
issue: damascenosteven-oss/YULING-mini-app#1
status: accepted
base: ed8cbb8b316e5b572f45a93faca550a41a3b265e
starting_candidate: 933109b1e9c3c2935c6cca0d12e1574acc277d6a
adr: not-required
---
# Issue #1：迁入待审代码

2026-10-26，所有者在 Codex 会话明确批准“将待审代码放入 YULING-mini-app”
及“恢复上传并交付审核 PR”计划，并要求实施。本仓库先作为审核副本。

## 来源和批准范围

- 本仓库 Issue：[导入 Mini-App 待审代码并保留审核来源](https://github.com/damascenosteven-oss/YULING-mini-app/issues/1)。
- 原应用 PR：[YuLing-Ai-Tech/mini-app#6](https://github.com/YuLing-Ai-Tech/mini-app/pull/6)。
- 原公开基线：`ed8cbb8b316e5b572f45a93faca550a41a3b265e`。
- 导入候选：`933109b1e9c3c2935c6cca0d12e1574acc277d6a`。
- Mac 参数修复：`005c7726de9af287f6059b239ea2cb06bb2a64ff`，已在候选历史中。
- 验证配对引擎：[YuLing-Ai-Tech/yuling-ai-ppt#5](https://github.com/YuLing-Ai-Tech/yuling-ai-ppt/pull/5)，
  `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`；引擎源码不导入本仓库。

本次批准的一次性例外仅允许：把原公开基线初始化为此前为空的目标 main；
随后从准确的 origin/main 创建 issue/1-review-import 工作树，原样导入已有公开历史。
历史提交无需重写以冒充本仓库审批。新增说明在专用工作树维护，本计划直接记录为 accepted。
审核分支允许推送及开 PR，不授权合并、部署、修改原仓库或关闭其 Issue。

## Critic Loop 与最小变更

我跑过／已查询：目标原先无分支，已有写入权限；原 PR 基线到候选共有 13 个提交、
45 个文件差异。所有者需要能逐项查看的审核入口，且原生 Mac 复验仍未完成。

| 方案 | 成本及影响 | 分数与决定 |
| --- | --- | --- |
| 保留基线 main，候选通过 PR 审核 | 保留历史，额外维护少量来源与核验说明 | 95/100，采用 |
| 保持空仓库 | 无迁入风险，但无法完成审核交付 | 30/100，不采用 |
| 候选直接进入 main | 步骤少，缺少待审差异并跳过本次审核分支 | 60/100，不采用 |
| 仅上传文件快照 | 文件可读，但丢失原提交来源 | 55/100，不采用 |

产品代码、依赖锁、Golden、渲染行为和 ENGINE_BASELINE.json 均与候选保持一致。
新增修改限于本计划、问答追加和 CONTRIBUTING 中的迁入状态说明。
没有新公共接口、架构、数据模型或行为变更，因此 adr: not-required；不新增功能测试。

## 目录问题与门禁缺口

首次初始化请求在执行前被本机 PreToolUse 钩子拒绝，Git 定位失败，没有产生远端分支。
只读对照已验证：仅指定工具 workdir 的帮助命令被拒绝；使用 Git -C 绝对目录能正常
显示帮助；错误目录仍被拒绝。原始钩子载荷未取得，内部参数丢失环节仍属推断。
恢复计划批准每条 Git 写命令直接使用绝对路径字面值，不修改钩子、检查器或信任设置。

本仓库尚未登记共享工程门禁；检查器诊断为 Repository not enrolled，不能记作通过。
所有者明确选择先交付审核副本，允许本次人工等效检查 Issue、分支、Accepted Plan、
来源一致性、敏感信息及验证结果。完整门禁建设另行安排。原 app-checks 工作流保留，
但工作流文件存在不等于本仓库 CI 已通过，也不等于分支保护或 CODEOWNERS 审批已配置。

## 验证与交付

使用 Node 22.23.3、pnpm 9.0.0、Python 3.12、Pillow 13.0.0、
Chrome for Testing 152.0.7977.64 和应用 Playwright 1.64.0。
明确设置 PPT_ENGINE_ROOT、PPT_PYTHON_PATH、PPT_CHROME_PATH。
在干净的提交版本上运行冻结安装、validate、portable、跨仓库、12 页 geometry、build、
完整及生产依赖审计；使用全新且位于两个仓库之外的目录验证候选两次独立 12 页捕获零差异。
核对最终文件差异白名单并扫描完整上传历史，记录实际命令、源码 SHA、退出码、数量及日志哈希。
测试结果在本计划追加；报告提交与实际测试提交分开标记。

PR 面向本仓库 main，正文使用 Closes #1，只关联本仓库迁入任务。提交 PR 后核对真实 CI，
交付仓库、Issue、PR、最终 SHA 和手机审核入口。旧文档中的测试和审批是原仓库历史证据。
原生 Mac 两轮新证据、Mac 批准与最终引擎 SHA 配对仍待完成，不能以 Windows 结果代替。

权限、远端引用、活动规则改变或钩子再次拒绝时停止受影响写入；结果不明先查询引用。
不强推、不覆盖他人提交、不自动清理工作树或分支。若需撤回新增说明，使用新提交或后续 PR，
保留导入历史、原基线和验证证据。

## 本次验证记录

待执行。此状态不构成任何测试、远端 CI 或 Mac 验收通过声明。
