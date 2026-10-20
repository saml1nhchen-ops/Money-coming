# Signal GEO 服务器部署准备

## 当前阶段

此目录提供 Linux Docker 私有试运行方案。它运行现有的三个服务和同一份前端，适用于阿里云 ECS/轻量服务器、腾讯云 CVM/轻量服务器或其他 Linux VM。没有购买云资源、创建公网部署或改动原 Sites 网址，也没有接通 GitHub 自动部署。

`.github/workflows/deployment-check.yml` 会在 Pull Request 和 main 更新时构建镜像、运行回归测试和服务检查；它仅验证，不发布到服务器。使用 GitHub 托管 runner 的额度和费用以账号计划为准。

应用目前没有用户账号、组织权限或租户隔离。两位合伙人访问的是同一套数据和模型配置。保留现有 loopback 配对限制，不把 8770–8772 暴露到公网；先通过 SSH 隧道验证完整工作流。它不是可直接用于对外服务的 SaaS 部署。

## 平台选择

| 平台 | 适配程度 | 国内外访问与注意事项 |
| --- | --- | --- |
| 阿里云 ECS / 腾讯云 CVM、轻量服务器 | 本方案的直接目标，运行 Docker 与持久化磁盘 | 可选大陆、香港或其他海外地区。海外用户也可访问；实际质量由地区和线路决定 |
| AWS Lightsail / EC2、DigitalOcean VM | 同样可使用此 Linux 方案 | 海外区域选择较多，大陆访问需实测；需自行维护系统与备份 |
| Render / Railway | 适合后续容器与 GitHub 集成 | 当前 host-network/SSH 方案不能原样使用。需增加统一 HTTP 入口、登录、持久化磁盘并适配平台端口及长任务限制 |
| Vercel / Cloudflare Pages | 适合静态前端 | 不能仅上传 dist 就运行现有 Python 常驻服务、子进程与本地文件任务；完整应用需另部署或改造后端 |

推荐先选香港或新加坡的 Linux VM，初始可评估 2 vCPU / 4 GB 内存及 40 GB 以上磁盘，实际容量按任务与构建峰值调整；这些不是压测结论。香港/新加坡也不保证所有模型服务可用，需核对各供应商的地区、账号和支付要求。不要据此绕过供应商地区限制。

大陆与境外用户都能否稳定打开网站，需要从实际用户网络测试，不能仅凭供应商品牌保证。中国大陆服务器使用域名对外提供网站通常需 ICP 备案；境外服务器通常不走大陆接入备案流程，具体以云厂商和业务要求为准。域名注册与应用托管是分开的，域名以后购买即可。

参考入口（具体产品、价格与区域以官方当前页面为准）：[阿里云 ECS](https://www.aliyun.com/product/ecs)、[腾讯云 CVM](https://cloud.tencent.com/product/cvm)、[Render Docker](https://render.com/docs/docker)、[Railway Docker](https://docs.railway.com/guides/dockerfiles)、[阿里云备案](https://beian.aliyun.com/)。

## 构建与私有启动

在具备 Docker Engine 和 Compose 插件的 Linux 服务器上，以有仓库读取权限的账号获取源码，进入仓库根目录：

```sh
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml exec workbench python deploy/run_services.py --check
```

构建安装 Python 3.12、Node 22 和 pnpm 10.11.0，从 tools/upstreams.lock.json 读取 NiubiGEO 的精确提交，用仓库附带的 pnpm 锁文件进行冻结安装。不会运行全部上游同步脚本，也不会改写原始上游锁文件。需要访问 Docker Hub、GitHub、Debian 软件源和 npm registry；不要关闭 TLS 或签名验证。

默认只安装自动出题所需的 NiubiGEO。其他开源工具的原生运行环境并未全部安装，界面仍会如实报告缺失。镜像不带模型密钥、旧数据库、任务记录、Git 历史或浏览器会话。

Linux host networking 用来保留现有服务之间的 loopback 通信。应用端口仍只监听 127.0.0.1；Compose 没有公网 ports 映射。此配置不面向 Docker Desktop 或 PaaS。

## 你和合伙人如何访问

给每人分别配置 SSH 账号和公钥，并仅开放必要的 SSH 访问。各自在自己的电脑执行，将 SERVER_USER 和 SERVER_HOST 替换成自己的服务器账号和地址：

```sh
ssh -N -L 127.0.0.1:8770:127.0.0.1:8770 -L 127.0.0.1:8771:127.0.0.1:8771 -L 127.0.0.1:8772:127.0.0.1:8772 SERVER_USER@SERVER_HOST
```

保持 SSH 连接，在各自浏览器打开 http://127.0.0.1:8772/ 。端口 8771 是 B.AI 配置，8770 是工具与直连模型配置。若这些本地端口被占用，先停掉自己原来的本机服务；现有前端依赖这些固定端口。

在网页中重新填写 API 密钥；不要放进 Git、Dockerfile 或聊天。现有密钥只保留在进程内存中，服务重启后需重新配置，两人共用配置并非独立账号。实际模型请求按供应商规则收费，启动和 readiness 检查本身不调用模型。

## 数据、重启与回退

四个命名卷保留任务、模型回答与诊断记录。正常更新使用 build 和 up -d；停止使用 docker compose -f deploy/compose.yaml down。不要使用 down -v，除非确实要删除全部持久数据。升级前停止服务并备份四个卷，限制备份访问权限。旧镜像不等于数据备份。

任一子服务退出会使容器退出，由 Compose 重启整组服务。长任务可能中断，已有代码保留中断状态，不自动重新调用付费模型。健康检查验证页面和三个已配对的只读 API，不代表真实模型凭据或所有上游工具已就绪。

## 之后接通自动部署与域名

先选定账号、地区和实际服务器，再配置：GitHub main → 测试与镜像构建 → 授权服务器拉取固定提交镜像 → 就绪检查 → 失败回滚。凭据保存在平台 Secrets 中，不能使用个人 GPT 会话凭据。当前目录尚未实现这条自动发布链路。

对外开放前还需要独立用户登录、权限边界、统一同源 API 入口、HTTPS、数据备份和真实访问验证；不要通过简单改绑 0.0.0.0 或移除现有配对校验来上线。届时可绑定自有域名，并配置 DNS 和 TLS；原 Sites 网址不能靠这份配置迁移为其他平台的托管地址。
