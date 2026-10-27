# 手机审核、发布与回滚测试站

本指南仅用于 Issue #8 的独立测试站。代理交付代码和 PR；所有者负责合并、
初始化、输入密钥、手动发布和真实业务验收。示例地址均为占位符。
1 核/1GiB 是受控试跑上限，不是容量保证；不增加容器 swap。
Mac 正式验收仍待完成，正式引擎锁不变。

## 1. 手机审核 PR

在 GitHub App 打开本仓库的 Pull Requests，进入部署 PR：

1. 阅读正文中的源码版本、测试结果、未完成验收和 `Closes #8`。
2. 点 Files changed，重点检查 `deploy/test/`、两个新增工作流和 Cookie 改动。
3. 点 Checks，确认**当前最新提交**的 `engineering-guard`、`app-checks`、`release-checks` 成功。
   绿色检查不等于真实服务器或 Mac 已批准。
4. 阅读手机初始化和恢复步骤，确认后由所有者合并。合并不会自动发布。

2026-10-27 已核实 main 要求 PR、最新分支、`engineering-guard` 和 `app-checks`，
禁止管理员绕过、强推和删除。此部署 PR 的 `release-checks` 成功后，由所有者在
Safari → Settings → Branches → main → Require status checks 中添加 `release-checks`
并保存。再查看当前提交检查后合并。测试环境保护仍需按下文单独配置。
不能把存在工作流文件当作已强制执行。原有检查器和钩子仍需正常通过。

## 2. 一次性初始化，由所有者在手机终端执行

使用先前可信的服务器终端。不要把下面操作交给聊天助手自动执行。
先确认当前服务器、Docker、原站、实际 Caddy 容器/网络、网关和 5000 端口。
不得调整其他网站、停止其他服务或扩大防火墙权限来使发布通过。

将审核合并后的仓库检出到一个新的独立目录；不要使用现有网站目录：

```bash
git clone https://github.com/damascenosteven-oss/YULING-mini-app.git ~/yuling-ppt-release-review
cd ~/yuling-ppt-release-review
git rev-parse HEAD
```

确认输出与手机上审核的 `main` 提交一致，阅读 `deploy/test/bootstrap.py` 和
`deploy/test/release.py`。后续升级受限接收程序需要另行审核；初始化不会覆盖已有不同版本。

创建仅用于此测试站的 ed25519 SSH 密钥对。私钥只进入 GitHub `ppt-test`
环境 Secret，公钥用于初始化。不要复用个人登录密钥，也不要把私钥发到聊天、
Issue、仓库文件或截图。自动发布使用的密钥不能要求交互输入口令。

以下命令中的容器、网络和公钥路径需替换为核实后的值：

```bash
sudo python3 deploy/test/bootstrap.py prepare \
  --caddy-container EXISTING_CADDY_CONTAINER \
  --caddy-network EXISTING_CADDY_NETWORK \
  --public-key /absolute/path/to/deployment-key.pub
sudo python3 deploy/test/bootstrap.py secrets
```

第二条命令交互输入 DeepSeek、COS、桶/地域和邀请码，输入不回显；
会话密钥自动生成。文件位于 `/etc/yuling-ppt-test/app.env`，root 所有、0600。
已有配置不覆盖。首轮不输入 Bocha；联网调研仍明确提示未配置。
COS 使用私有桶、仅该测试项目所需权限，不能用云账号管理员权限。

`prepare` 输出主机公钥及指纹。通过这个可信终端核对后，将公钥保存为
GitHub 的已知主机记录；不能在工作流里临时扫描主机公钥并直接信任。

## 3. 用 Safari 设置 GitHub 测试环境

打开仓库 Settings → Environments → New environment，名称 **`ppt-test`**。
限制部署分支为 `main`；账号方案允许时添加必需审批者。
在该环境内添加三个 Secrets：

| 名称 | 内容 |
| --- | --- |
| `DEPLOY_HOST` | 核实的服务器 IP 或 SSH 主机名，不含协议和端口 |
| `DEPLOY_SSH_KEY` | 测试站专用 SSH 私钥全文 |
| `SSH_KNOWN_HOSTS` | `服务器IP ssh-ed25519 公钥内容`，与可信终端输出一致 |

SSH 使用 22 端口和受限账户 `yuling-ppt-deploy`。应用 API 密钥保留在服务器，
不放入 GitHub 构建环境。SSH 不可达就停止，排查访问路径；不自动放开安全组。

## 4. 接入测试域名

确认测试子域名 DNS 指向服务器，原站正常。仅追加测试域名：

```bash
sudo python3 deploy/test/bootstrap.py connect-site \
  --domain ppt-test.example.com \
  --existing-site https://existing.example.com
```

脚本记录备份和哈希，验证配置，保留单文件挂载的文件身份，核对容器实际内容，
热加载后再检查原站。不重启 Caddy、不重写原站。此时应用尚未发布，测试站可能返回 502。

## 5. 手机手动发布

Issue #12 修复合并后，先由管理员核对合并提交并升级接收程序，再启动新发布。
旧接收器缺少版本能力信息时，新客户端会在上传前停止并提示升级。
管理员在已审核的检出目录执行（旧哈希必须先通过可信终端核对）：

```bash
sudo sha256sum /usr/local/libexec/yuling-ppt-release.py
sudo python3 deploy/test/bootstrap.py upgrade-receiver --expected-sha256 <已核对的旧程序完整SHA256>
```

升级使用与发布相同的操作锁；备份保存在 `/etc/yuling-ppt-test/receiver-<旧哈希>.before`。
哈希不符或操作正在运行时停止；安装校验失败恢复旧程序。升级不改秘密、SSH 授权或 Caddy。
管理员检查新版本、受限入口状态和原站健康后，所有者才继续以下手机步骤。

Safari 打开仓库 → Actions → **PPT test site — publish or rollback**：

1. 点 **Run workflow**。
2. Branch 选择 **main**；operation 选择 **publish**。
3. 确认运行。先在 GitHub 构建并验证镜像，再执行受限服务器操作。
4. 查看 build 和 release 两个任务；若有环境审批提示，由指定审批者确认。
5. 打开测试网址，完成下节验收。App 未显示按钮时使用 Safari 的桌面网站模式。

首次失败记录仍绑定旧提交，**不要重跑那条旧记录**。修复合并和接收器升级完成后，
使用 `Run workflow → main → publish` 创建新运行。
新工作流按 build 返回的固定 artifact ID 下载；只重跑失败的 release 时沿用该成功构建的 ID，
全量重跑使用新 build 的 ID。ID 缺失、产物过期或摘要/版本不符均停止，不选择最新产物兜底。
只重跑失败任务在本地只能模拟；真实 GitHub 重跑结果单独记录。

release 日志显示 `receive`（收包）、`archive`（归档校验）、`image`（镜像校验）、
`normalize`（整理）和 `stored`（保存）阶段，并报告字节数及累计秒数。
上传最长 45 分钟，120 秒无新数据即失败；收包后的校验整理最多 15 分钟。
客户端上传最多 65 分钟，release 任务最多 90 分钟，部署/回滚接收端仍最多 15 分钟。
这些是有界设计预算，尚不证明真实服务器网络能在预算内完成。
失败时保留失败阶段、字节数和错误代码交给维护者检查，不连续重试或自行增加时限。

工作流只接受 main，发布串行执行，服务器不编译代码、不登录镜像仓库。
归档、应用 SHA、引擎 SHA、内容摘要不匹配会拒绝。上传失败可重试相同产物；
结果不明确时先看任务输出和服务器 `state.json`，不要连续点击发布。
构建的候选引擎固定为 `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192`，
与正式锁的区别记录在发布清单中。

## 6. 所有者验收与容量观察

先只运行一个任务，生成普通 12 页 PPT。确认 DeepSeek 调用、COS 写入/读取、
手机预览和分享都成功，且原有网站仍可用。健康接口成功不能代替这些检查。
观察生成前、生成中和结束后的内存；不要仅看生成前的一次 `free` 输出。

```bash
free -m
docker stats --no-stream yuling-ppt-test
docker inspect --format '{{.State.OOMKilled}} {{.State.Status}}' yuling-ppt-test
docker exec yuling-ppt-test sh -c 'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events'
```

暂停旧 PPT 后最低要求可用内存 768MiB、磁盘 8GiB；这是进入试跑的最低检查，
不是给 1GiB 应用预留了足够长期余量。超过限制可能超时或被终止。
失败不自动提高上限、启用额外 swap、清理其他项目或停用其他服务。
仅绑定 Caddy 网关的 5000 端口；发布程序在 GitHub 外部探测该端口，
外部可直接连接时拒绝继续，并要求检查绑定/网络。

## 7. 回滚与首次失败恢复

已有上一成功版：在同一 Actions 工作流选择 **main → rollback**。
无需重新构建，恢复上一成功版本；允许测试站短暂中断。发布失败会自动尝试
恢复之前的 PPT，恢复失败则保留 pending 状态并报错，需要所有者检查。

首次发布失败、没有上一版时，停止失败容器后，由所有者撤回新增站点：

```bash
sudo python3 deploy/test/bootstrap.py restore-site
```

若 Caddy 已被其他人修改，脚本拒绝覆盖；保留备份并人工核对。
不要通过删除数据库、执行 Docker 全局清理或重启原站处理测试站失败。

## 验证范围

本机测试、GitHub CI、实际部署和所有者验收分别记录。PR 正文提供实际结果，
本指南的步骤描述本身不证明已执行。长期清理定时任务不在本轮范围。

参考：[GitHub 手动运行工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)、
[Docker 内存限制](https://docs.docker.com/engine/containers/resource_constraints/)、
[Caddy 热加载](https://caddyserver.com/docs/command-line)。
