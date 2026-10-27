# 手机运行三段网络测速

此入口只测 4MiB 随机文件，不发布、不构建应用镜像。先审核并合并本 PR，确认当前提交的
engineering-guard、app-checks、release-checks 均成功。服务器升级和运行均由所有者操作。

## 1. 准备独立 COS 权限

在腾讯云 CAM 创建仅用于测速的子用户及自定义策略，不选择 AdministratorAccess 或整桶全权限。
关联下列策略，仅允许上海私有桶中的 transfer-probe/ 对象上传、读取和删除：

```json
{
  "version": "2.0",
  "statement": [{
    "effect": "allow",
    "action": ["name/cos:PutObject", "name/cos:GetObject", "name/cos:DeleteObject"],
    "resource": ["qcs::cos:ap-shanghai:uid/1494859304:yuling-ppt-test-1494859304/transfer-probe/*"]
  }]
}
```

不要给该子用户关联其他扩大权限的策略。桶保持私有；先在控制台确认版本控制未开启。
若桶已开启版本控制，暂停测速并反馈：普通删除可能只创建删除标记，不能承诺清除了历史版本。
本轮不修改桶策略、版本控制或生命周期。资源写法依据[腾讯云策略示例](https://cloud.tencent.cn/document/product/436/71307)。

手机 Safari 打开个人仓库 Settings → Environments → ppt-test → Add environment secret：

| 名称 | 值 |
|---|---|
| PROBE_COS_SECRET_ID | 新测速子用户的 SecretId |
| PROBE_COS_SECRET_KEY | 新测速子用户的 SecretKey |

沿用既有 DEPLOY_HOST、DEPLOY_SSH_KEY、SSH_KNOWN_HOSTS，保持仅 main 可用。
不要把应用 COS 密钥复制过来，不要把密钥或完整签名地址发到聊天、Issue、截图中。
这是普通 COS 请求，可能产生少量请求/存储/流量费用，不启用付费加速服务。

## 2. 在手机终端升级受限接收程序

以下命令在你已经登录的 ubuntu 终端执行，每一步确认结果后继续。

```bash
git -C "$HOME/yuling-ppt-release-review" status --porcelain
git -C "$HOME/yuling-ppt-release-review" fetch origin main
```

第一条必须无输出。第二条失败就停止，不覆盖本地改动。然后：

```bash
git -C "$HOME/yuling-ppt-release-review" merge --ff-only origin/main
git -C "$HOME/yuling-ppt-release-review" rev-parse HEAD
sudo sha256sum /usr/local/libexec/yuling-ppt-release.py
```

核对 HEAD 为 GitHub 上已审核合并、包含本测速 PR 的版本。
预期旧接收器 SHA-256 是 d4526feed16f92b0131be01f12501a1deb1b74017a48f1ed0d0a5aad26174a9b。
若与此不同且不是本次已升级版本，停止反馈，不把未知哈希直接替换进命令。

```bash
sudo python3 "$HOME/yuling-ppt-release-review/deploy/test/bootstrap.py" upgrade-receiver --expected-sha256 d4526feed16f92b0131be01f12501a1deb1b74017a48f1ed0d0a5aad26174a9b
sudo python3 /usr/local/libexec/yuling-ppt-release.py --self-check
curl --max-time 20 -sS -o /dev/null -w 'HTTP %{http_code}\n' https://zhuwenjie.online
```

预期能力列表新增 bounded-probe-v1，receiver_version 仍为 2；原站返回 HTTP 200。
发布正忙或旧哈希不符会拒绝升级；备份和失败恢复继续生效。此步骤不会启动 PPT 或重启 Caddy。

## 3. 手机触发一次测速

Safari 打开仓库 Actions → **PPT 网络测速** → Run workflow → Branch 选择 **main** → Run workflow。
App 没有触发按钮时使用 Safari。不要点击 “PPT test site — publish or rollback”。

每轮顺序为 SSH、COS 上传、COS 下载，三轮共九个样本；正常传输量 36MiB。
每段最多五分钟，失败不重试；整个工作流最多六十分钟。认证/校验异常会停止；普通传输超时保留失败记录。
与发布共用队列，不会同时执行。文件未完整接收时不会把部分速度算成成功测速。

## 4. 看结果，不急着重跑发布

打开运行 Summary 中的中文表格；Artifacts 中的 result.json 和 summary.md 保存七天。
结果包含时间、版本、字节、耗时、校验、DNS/连接地址和清理情况，不含签名或密钥。
SSH 建连耗时为客户端总时间减接收端时间的估算，包含命令启动开销，不能当作精确 TCP 握手时间。
COS 上传的 SHA-256 只有在同轮服务器下载校验成功后才标记已验证；MD5 是上传服务响应的附加核对。

每段三次全成功才汇总中位数与范围。按 931635200 字节估算，中转两段合计≤30分钟、比直传快≥4倍，
才建议另行安排大文件验证；不会自动切换发布方案。小文件测试不等于发布成功，也不证明运营商限速或丢包。

同地域内网是[腾讯云文档描述](https://intl.cloud.tencent.com/zh/document/product/1103/41257)，仍以报告中的解析和实际连接地址核对，不能只凭地域认定。

若取消或清理失败，查看 outstanding_objects，仅处理列出的 `transfer-probe/<run>-<attempt>-<round>.bin`。
严禁清空整个桶。强制终止可能连报告上传都无法完成；此时按运行编号及 attempt 确认这三个精确对象，
在 COS 控制台核对后由所有者删除。签名十分钟失效，持久密钥仍需在测试结束后按需由所有者停用。
不自动执行整桶清理、密钥轮换、服务器扩容或再次发布。
