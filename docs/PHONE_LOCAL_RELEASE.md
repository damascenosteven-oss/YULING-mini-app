# 手机触发，电脑执行测试站发布

适用：Issue #16 合并后。应用代码仍来自
`damascenosteven-oss/YULING-mini-app` 的 `main` 完整提交。
引擎固定版本、12 页重复捕获和服务器受限接收程序沿用现有部署链路。
此页不代表服务器已经发布，也不代表 Mac 验收。

## 一次性准备

1. 电脑保持登录、联网，打开 Docker Desktop 并确认 Ubuntu WSL 可运行 `docker version`。
   发布时允许锁屏；睡眠、关机或 Docker 停止会使手机请求超时失败。
2. 在 Ubuntu WSL 中检出审核合并后的仓库 `main`。使用 Python 3.12、Git、
   OpenSSH 和 Docker Desktop 的 WSL 集成；构建在本机 Docker 中进行。
3. 创建**仅限本仓库**的 GitHub fine-grained PAT，授予 Contents: read、
   Actions: read、Checks: read、Deployments: read and write。只保存于电脑的
   0600 文件；不能放在仓库、Issue、聊天、截图或 Actions Secret。
4. 将此前专用的 `yuling-ppt-deploy` 私钥和已经核对的 SSH 主机公钥记录
   安全存入电脑的独立 0600 文件。**不要使用桌面管理员 SSH 密钥**。
   服务器应用密钥保持在服务器，不复制到电脑。
5. 在电脑 WSL 的仓库外建立 0600 的 JSON 配置文件，例如：

```json
{
  "token_file": "/home/USER/.config/yuling-ppt/github-token",
  "ssh_key": "/home/USER/.config/yuling-ppt/deploy-key",
  "known_hosts": "/home/USER/.config/yuling-ppt/known_hosts",
  "host": "115.159.143.24",
  "trusted_client": "/home/USER/YULING-mini-app/deploy/test/ssh-client.py",
  "state_dir": "/home/USER/.local/state/yuling-ppt-relay"
}
```

   把 `USER` 替换为实际 WSL 用户。配置文件只存路径，密钥文件及配置文件权限
   均为 0600；状态目录权限为 0700。首次运行前核对配置中的脚本是已合并版本。
   状态目录记录已接过的请求 ID；不要为了重试删记录，需由手机发起新请求。

## 每次发布

1. 在电脑的 Ubuntu WSL 运行：

```bash
python3 /home/USER/YULING-mini-app/deploy/test/local-bridge.py \
  --config /home/USER/.config/yuling-ppt/config.json
```

   看到接力程序持续运行后，再在手机 GitHub App 或 Safari 中进入本仓库
   **Actions → PPT test site — publish or rollback → Run workflow**。
2. 选择 `main` 和 `publish`。工作流只提交小型请求；镜像在电脑构建，
   电脑校验后通过现有受限 SSH 入口直接上传。手机 Actions 运行会等待电脑
   回报真正成功或失败。构建和两次 12 页捕获可能需要较长时间。
3. 成功后打开 `https://ppt-test.zhuwenjie.online`，用邀请码登录，
   实际生成一份普通 12 页 PPT，核对 DeepSeek、COS 写入/读取、手机预览、
   分享、资源占用及原站健康。这些业务检查未过时不能称发布验收通过。

## 回滚与失败

在同一手机工作流选择 `main`、`rollback`。电脑会复核请求并调用服务器现有
受限回滚操作；不重新构建镜像。取消、电脑离线、main 更新、门禁缺失、
请求超时或校验错误都停止，不自动重试或切换版本。
上传完成后若请求失效，程序不会切换应用；检查服务器状态后由所有者决定
是否发起新的手机请求。

若电脑程序显示失败，记录请求 ID、固定失败阶段、Actions 链接和服务器状态；
不要粘贴 PAT、私钥、GitHub 请求头或应用秘密。首次失败无上一版时沿用
`docs/PHONE_TEST_RELEASE.md` 的站点恢复步骤。

## 安全边界

手机工作流只能由仓库所有者从 `main` 手动触发，使用现有 `ppt-test`
GitHub Environment 和串行队列。电脑再次验证运行身份、受保护的当前 main、
`app-checks` 和 `release-checks` 在该完整提交上的结果、有效期和重复请求；
`engineering-guard` 是合并前的 PR 检查，由 main 分支保护强制执行。
电脑只使用受限部署用户；管理员密钥不参与发布。
正式发布和回滚由所有者手机触发，合并 PR 不会自动部署。
