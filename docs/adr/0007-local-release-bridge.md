---
issue: https://github.com/damascenosteven-oss/YULING-mini-app/issues/16
status: accepted
---

# 电脑接力执行手机触发的测试站发布

## Critic Loop

问题：现有 GitHub 云端至服务器的 931635200 字节包，在 2700 秒仅传约 67MiB，发布超时。实测电脑经相同 SSH 协议传真实镜像包前 128MiB 达约 6.64MiB/s，说明不能简单归咎于 SSH；完整包速度及受限接收器仍需验证。

保持现状 25/100：零修改但重复超时。COS 中转 30/100：4MiB 上行近 282 秒并返回 HTTP 错误，增加凭据和路径但未证明更快。
独立私库 Runner 88/100：标准 Actions 执行和手机体验，但要求证实私库远端保护及维护第二仓库。账号套餐未能只读确认，故本次不采用。
现有公开仓库加电脑接力 82/100，接受：保留已强制执行的 main 门禁和原手机入口，电脑不注册在公开仓库为自托管 Runner；代价是维护有界轮询、最小权限 GitHub Deployment 状态及本机后台程序。

## 决定

GitHub 工作流只创建绑定完整应用 SHA 的短期部署请求并等待状态。电脑在已登录且 Docker Desktop 运行时读取请求，重验身份、main、检查和未处理状态，在本机运行既有固定镜像构建/验证，再经受限 SSH 上传和调用部署或回滚。应用密钥留在服务器，电脑 GitHub/SSH 凭据不进仓库或产物。无自动重试；失败保持已有成功版。

部署请求和处理结果使用 GitHub Deployment 与 status API；操作仅 publish/rollback。必须在运行编号、尝试编号和请求 ID 上幂等；过期或取消后禁止迟到发布。工作流结束状态反映电脑真实结果。只在所有者合并后启用真实手机触发；Windows/电脑验证不构成 Mac 接受。
