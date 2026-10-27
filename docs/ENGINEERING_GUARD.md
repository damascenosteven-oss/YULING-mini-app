# 工程门禁维护与手机审核

本仓库复用 engineering_guard.py 1.0.0。检查器 SHA256：
`502ebbbac181494153662d7b08056f8a303a7039af80e18106c1f214c42f5a29`。
运行环境为 Python 3.12 和 Git（支持 `git hook run --to-stdin`）。
检查器快照不含私有台账；策略包含本仓库 Issue #9 与 Issue #8 的所有者批准记录。

## 检查范围与边界

pre-commit 检查暂存树，pre-push 检查待推送提交并拒绝推送或删除 main/master。
PR 工作流 `engineering-guard` 检查实际 PR head/base、分支、Accepted Plan/ADR
及匹配的 Closes。测试通过实际安装的 Git 钩子和共享检查器 CI 入口。
工作流只有只读 contents 权限，不使用应用密钥，也不发布产品。

本地安装覆盖同一 Git common-dir 的全部工作树，不自动保护其他人的克隆。
Codex 继续使用现有已信任适配器，不改变全局钩子、信任或私有台账。
只约束检查器编码的条件，不证明代码无缺陷、不代替所有者审批，不保证防御
能修改本地文件或 PR 工作流的恶意拥有者。策略中的批准声明必须由所有者审核。

GitHub 分支保护须由所有者设置；仅有工作流不等于强制禁止合并。
此前 Dependabot PR 没有新增豁免，后续触发本工作流也必须符合生命周期要求。

## 手机设置 main 保护

1. 在 Safari 登录 GitHub，打开本仓库 Settings → Branches；必要时请求桌面网站。
2. 添加 branch protection rule，Branch name pattern 填 `main`。
3. 勾选 Require a pull request before merging。
4. 勾选 Require status checks to pass before merging。等待本 PR 运行成功后，
   从实际检查列表选择 `engineering-guard` 和 `app-checks`，核对来源为 GitHub Actions。
5. 勾选 Do not allow bypassing the above settings；保持 Allow force pushes 和
   Allow deletions 关闭。保存后重新打开规则确认。
6. 如果启用必需审批，必须安排另一位有权限的审核者；作者不能批准自己的 PR。
   无第二位审核者时，不应设置一个永远无法满足的审批人数要求。

按钮以 GitHub 实际页面为准。官方说明：
[管理分支保护规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)。
完成设置前，本交付只表示本地钩子已验证、CI 已运行，不表示远端强制保护已生效。

## 后续 Issue 与恢复

所有者已合并门禁 PR #10。Issue #8 原部署草稿完整保留，续作从最新 origin/main
创建新工作树，登记 Accepted Plan 与批准策略；部署 ADR 已顺延为 0004。
审批策略变更使用正式 `update` 入口，冻结时间不变。部署代码交付仍不授权代理
合并、初始化服务器或实际发布。

新克隆需要由有权限的维护者检查已有钩子，然后用正式 `install` 入口登记。
安装会保留原钩子备份；失败时保留现场，先诊断，不改 hooksPath 绕过检查。
卸载须经所有者另行批准并使用正式 `uninstall`，不能删除私有台账来恢复提交。
实际本机安装回执及日志保存在仓库外，交付报告只记录脱敏结果和哈希。
