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
   同目录下的 `source-cache/` 保存应用和固定引擎的完整 Git 对象。不要手工改写缓存；
   来源不符或对象损坏时接力会停止，不会自行改用旧提交。
   同目录下的 `runtime-cache/` 保存校验过的固定 Node、Chrome 和 pnpm 文件，
   仅预热时允许补齐；正式发布只读取。缓存缺失或校验失败时该次请求失败。
   `dependency-cache/` 保存按 `package.json`、`pnpm-lock.yaml`、运行环境锁和
   Linux 架构绑定的 pnpm 包。预热时验证完整离线安装；正式发布只读缓存，
   镜像内使用冻结离线安装。不要手工修改这两个缓存。

6. 首次手机发布前，在同一 WSL 环境准备源码、运行环境和依赖缓存：

```bash
python3 /home/USER/YULING-mini-app/deploy/test/local-bridge.py \
  --config /home/USER/.config/yuling-ppt/config.json --warm-cache
```

   这个命令实时核对受保护 `main` 和该提交的应用与发布检查，准备应用和固定引擎源码。
   同时依据 `runtime-lock.json` 下载并核对固定运行环境文件；每个缺失文件最多尝试三次。
   依赖预取依据锁文件执行 `pnpm fetch`，每次最多五分钟、最多三次；
   只有冻结离线安装成功才接受缓存。预热需要联网，正式镜像安装依赖时不下载包。
   若已有另一轮构建中经过校验的下载目录，可在上述命令末尾增加
   `--runtime-seed-dir /绝对路径/runtime-downloads`，由程序再次校验哈希后复制到缓存。
   这个命令不创建发布请求、不构建镜像，也不连接服务器。若检查或下载失败，先看错误阶段，
   不要把缓存命中当作 GitHub 检查通过。

## 每次准备和发布（Issue #24 合并并更新电脑接力后）

1. 在电脑的 Ubuntu WSL 运行：

```bash
python3 /home/USER/YULING-mini-app/deploy/test/local-bridge.py \
  --config /home/USER/.config/yuling-ppt/config.json
```

   看到接力程序持续运行后，再在手机 GitHub App 或 Safari 中进入本仓库
   **Actions → PPT test site — prepare, publish or rollback → Run workflow**。
2. 先选择 `main` 和 `prepare`。电脑获取固定源码、准备依赖、执行完整及生产审计、
   正式构建和两次 12 页捕获。成功摘要显示“准备版本”、完整提交和审计有效期，
   此阶段不连接服务器，也不代表测试站已更新。
3. 准备成功后，重新点 **Run workflow**，选择 `main` 和 `publish`。
   电脑只校验同一提交的完整包，通过受限 SSH 上传并启用；不重新下载、构建或审计。
   若 main 已变化、包缺失或审计超过 24 小时，工作流拒绝发布并提示先准备。
4. 发布成功后打开 `https://ppt-test.zhuwenjie.online`，用邀请码登录，
   实际生成一份普通 12 页 PPT，核对 DeepSeek、COS 写入/读取、手机预览、
   分享、资源占用及原站健康。这些业务检查未过时不能称发布验收通过。

完整包在状态目录的 `prepared-releases/`，只保留最近两个已接受版本。
同一提交 24 小时内再次 prepare 会校验复用；过期后再次 prepare 只重新执行
两份审计，不重建包或重复捕获。审计失败仍停止，损坏包不能借刷新审计恢复。
不要手工编辑包、摘要、审计或接受记录。

prepare 使用独立的请求环境 `ppt-test-local-prepare`；publish/rollback 使用
`ppt-test-local-relay`。它们共用现有 `ppt-test` 工作流保护和令牌权限，不需增加密钥。
旧 schema 1 的工作流记录不重跑；必须从合并后的 main 新建请求。

## 回滚与失败

在同一手机工作流选择 `main`、`rollback`。电脑会复核请求并调用服务器现有
受限回滚操作；不重新构建镜像。取消、电脑离线、main 更新、门禁缺失、
请求超时或校验错误都停止，不自动重试或切换版本。仅在缺少指定源码提交时，
Git 获取最多尝试三次，每次限时 90 秒，等待 2 秒、5 秒；上传、服务器切换和
整个发布请求仍只执行一次。
准备时审计只对网络错误、429/5xx 最多尝试三次，每次 90 秒，间隔 2/5 秒；
发现漏洞或响应不完整立即失败。审计移出 Docker 缓存层，每次需要刷新时实际联网。
预热运行环境文件时每次下载限时 10 分钟，连续 120 秒无进展即失败，
两次重试间隔 2 秒、5 秒。某次请求构建失败会记为失败，接力继续等待新的手机请求；
不会重试该请求。若缓存提示正在使用，先确认是否另有预热或发布进程，不要直接删除锁文件。
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
