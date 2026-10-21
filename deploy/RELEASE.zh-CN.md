# 正式 Release 自动更新腾讯云后台

状态：部署会话已确认 [v0.3.0](https://github.com/saml1nhchen-ops/Money-coming/actions/runs/39652604630) 构建、部署和服务器版本核对成功，原数据卷保留。**线上故障回滚演练尚未完成**。以下安装步骤用于新服务器或重建连接，不要在已配置的服务器上重复初始化。

## 本次保持登录变更

Pages 默认入口转入团队页，后台地址预填。前端兼容 v0.3.0 原登录协议；30 天设备凭证与后台重启恢复，需要发布包含新后台代码的下一版正式 Release 后才生效。设备会话库新增于现有 runtime 卷，不改报告与预算结构。退出只撤销当前设备；修改服务器团队密码并重启会使所有旧设备凭证失效。旧版本回滚可能要求临时重新登录，不会删除报告或该会话库。

自动登录恢复不会触发模型采样。本次离线检查不能代替线上 30 天登录、密码轮换或故障回滚演练。

## 行为

只有 GitHub 正式 Release 的 `published` 事件触发。普通 push、草稿和 prerelease 不部署。版本标签使用 ASCII 字母/数字开头，后面可用字母、数字、点、下划线和连字符，最长 128 字符。Actions checkout 标签实际 commit、构建镜像，部署固定 SHA256 digest，不使用 latest。

Actions 使用 GitHub 提供的 GITHUB_TOKEN 推送 GHCR。服务器在已有版本仍运行时先拉镜像并核对 commit；拉取失败不动应用。之后通过私有维护信号停止接收新分析，最多等 30 分钟让原任务完成，超时保持旧版本并重新开放。新容器从启动起保持维护，私有就绪与公网 HTTPS 都通过后才放行。不会为了检查健康发聊天请求。

失败时用服务器保留的旧镜像 ID 重建原后台，检查通过后恢复服务，本次 Actions 仍标失败。回滚失败则保持维护并阻止后续自动部署，等待人工恢复。仅回滚程序，**不回滚业务数据**；报告、预算和 Caddy 证书卷不删除。涉及不兼容数据迁移的版本不适用这条自动链。

服务器项目固定为 `geo-backend`，目录默认 `/home/ubuntu/geo-backend`，更新前后核对 `/app/runtime` 的实际卷名。仅重建 backend，不重建 HTTPS 服务。发布清单绑定 Release ID、标签、发布时间、commit 与 digest，保存在 Actions 制品和服务器；同 Release 改 digest、迟到的旧正式版本会被拒绝。服务器用 flock 串行部署；Actions 不取消正在运行的发布，多个等待事件可能被最新事件替换，不承诺每个 Release 都排队执行。

## 一次性安装：在已登录的腾讯云终端执行

当前首次部署的旧镜像没有维护信号处理，**不能直接向它发送 SIGUSR1**。自动脚本会先检查 `signals-v1` 能力，缺失就拒绝，不会发送信号杀掉旧进程。

1. 安排一次没有分析任务的维护窗口，让团队暂时不提交新分析。在腾讯云终端确认无活跃任务后，拉取本次已验收代码，手动构建并启动一次新后台：

   ```sh
   cd /home/ubuntu/geo-backend
   git pull --ff-only origin main
   sudo docker compose -p geo-backend up -d --build
   sudo docker compose -p geo-backend exec -T backend python3 tools/deploy_control.py probe
   ```

   此步骤只用于旧版的一次性引导。不要在运行分析时做，也不要删除命名卷。后续自动部署不在服务器构建。

2. 在可信本机生成专用 Ed25519 部署密钥。私钥保留在本机与 GitHub production secret 中，**不要发聊天、提交 Git 或放进镜像**。仅把 `.pub` 公钥传到服务器。安装：

   ```sh
   sudo bash deploy/install-release.sh /路径/signal-release.pub
   ```

   安装器创建受限 `signal-deploy` 用户、禁止该密钥的转发/PTY，通过 forced command 只允许固定 sudo 部署入口及校验过的发布参数，不提供任意远程 shell。不把用户加入 docker 组，不修改 B.AI 密钥或团队密码，不自动重启应用。

3. 首次发布构建后 GHCR 包通常默认为私有。选择一种并**从腾讯云服务器实测 docker pull**：

   - 保持私有：用仅有 `read:packages` 的凭据在服务器执行 `sudo docker login ghcr.io`，不把它传给前端或构建镜像。
   - 因源码本身公开，也可由仓库所有者将对应 backend 容器包设为公开，然后验证匿名拉取。工作流不会擅自改变包可见性。

   拉取不可达/未授权是安装阻塞，不能以镜像已上传代替验证。备用镜像仓库需要同步改工作流与严格白名单，不能临时传入任意 registry 绕过校验。

4. 在 GitHub 仓库 Settings → Environments 创建 `production`，配置：

   | 类型 | 名称 | 内容 |
   | --- | --- | --- |
   | Variable | `SIGNAL_DEPLOY_HOST` | `43.154.242.184` |
   | Variable | `SIGNAL_DEPLOY_USER` | `signal-deploy` |
   | Variable | `SIGNAL_DEPLOY_PORT` | 实际 SSH 端口，默认 22 |
   | Secret | `SIGNAL_DEPLOY_SSH_KEY` | 专用部署私钥 |
   | Secret | `SIGNAL_DEPLOY_KNOWN_HOSTS` | 经腾讯云终端核对指纹的 SSH known_hosts 记录 |

   从服务器控制台用 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 取得可信指纹，再核对收集的 known_hosts。不要在 Actions 里用未经核对的 ssh-keyscan 临时信任主机，也不要关闭 StrictHostKeyChecking。SSH 必须可从 GitHub runner 到达；没有该连接时不声称启用。

## 第一次正式验收

发布一个正式 Release，检查 build 和 deploy 都成功，并验证公网 `/healthz` 的 revision 等于该标签 commit。此检查不运行付费分析。在已授权的维护窗口再验证一次故障版本会回滚、原卷中的报告和预算仍在，之后才算完整启用。生产环境可保留人工审批保护，需要时由管理员配置。

若首次 build 已成功但缺少 registry/SSH 设置，先补安装，再重跑失败的 deploy job，使用同一镜像 digest，不需要重新发起模型分析。同一 Release 不允许用重新构建出的另一 digest 覆盖；需要改程序时发新的正式 Release。

## 后续重启与维护

自动部署使用 `.deploy/compose.release.yaml` 固定当前镜像，该文件也保留启动维护及本次发布的随机标识。只有健康检查通过后写入的只读健康回执与当前标识、版本完全匹配，容器重启才自动恢复接收任务；未完成或旧回执都继续维护。后续手动操作应同时传入这个 override；不要只运行原始 compose.yaml 把镜像切回旧标签。

仅在核对服务健康、版本、预算和没有活跃任务后，管理员可通过容器内精确目标的 SIGUSR2 解除维护。发布状态保存在 `.deploy/release-status.json`；`preparing` 等遗留非终态或 `rollback_failed` 必须先人工恢复并核验，再由管理员处理该状态文件，不能盲目删除状态或清卷重来。主机断电、SIGKILL 和磁盘损坏可能中断回滚，需要人工恢复，不保证自动恢复所有主机故障。

## 前端 Pages 的界线

这条流程更新的是腾讯云后台。当前 GitHub Pages 前端仍按 main 更新；**不能说普通提交完全不影响线上前端，也不能说 Release 已同步发布前后端全站**。API 必须兼容当前前端。若要前端也仅随 Release 发布，还需切换 Pages 为 Actions 发布并实测另一条发布流程，不能只改后台脚本就宣称完成。

## 本地验证

`python3 -m unittest discover -s tests -p 'test_release_deploy.py'` 用合成 Docker/TLS 响应检查触发配置、精确版本、幂等、拉取失败、忙任务超时、私有与公网健康失败回滚、回滚失败拦截及锁。`test_deploy_control.py` / `test_remote_gateway.py` / `test_remote_service.py` 检查真实本机 HTTP 与维护准入并发。`python3 tests/container_release.py` 在断网的真实容器中检查 supervisor 信号、启动维护、健康回执与重启恢复；旧生命周期验收为 `python3 tests/container_remote.py`。这些不等于腾讯云真实发布成功。
