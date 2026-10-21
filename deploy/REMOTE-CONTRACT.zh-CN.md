# CREMO-END-TO-END-02：远端单团队工作台契约

状态：架构交接，可实现；未部署、未调用真实付费模型、未完成 Cremo 实采。请求执行档为 Sol/high，未收到实际模型元数据，不计模型核验通过。

## 1. 边界与归属

- GitHub Pages `https://saml1nhchen-ops.github.io/Money-coming/` 保持静态前端；默认 overview 与根 index 跳转保留。在 research 页内连接远端 HTTPS 后台。
- 一个用户与合伙人共用的私有团队工作台。全部授权成员可查看、导出、停止同一工作台任务，报告共享；不宣称个人隔离或多租户。
- 单实例容器：托管 HTTPS 终结 → stdlib Python 网关（唯一公网端口）→ 原有 127.0.0.1:8772 → 原有 8771 B.AI / 8770 native。三条 loopback 端口不映射公网；网关不提供任意反向代理、文件或 shell 路径。
- 前端唯一归属：前端实现者仅改目标仓库 dist/ 下连接、状态和 research 流程；不改入口默认路由。后端唯一归属：后端实现者仅改 tools/ 下新增 remote gateway/launcher/部署辅助脚本；既有服务模块如需修改先由根协调。根唯一归属：旧 GEO 已验收功能同步、公共 fixtures/tests/docs、Dockerfile/.dockerignore/render.yaml、Git 与最终集成。不得互改。

## 2. 认证与边缘限制

服务器环境变量：`SIGNAL_BAI_API_KEY`、`SIGNAL_WORKSPACE_PASSWORD`（至少16字符）、`SIGNAL_PUBLIC_HOST`、`PORT`；`SIGNAL_DAILY_CALL_LIMIT` 为非负整数，默认126（两次完整63调用任务），0为禁用新付费任务；模型固定ID可用 `SIGNAL_GPT_MODEL` / `SIGNAL_GEMINI_MODEL` 显式覆盖，但必须存在于当前密钥的实际模型目录。不得将 secret 值写进仓库、镜像、前端、响应或日志。

- 登录 POST `/api/workspace/login`，JSON `{password:string}`；成功200 `{token:string,expires_at:ISO8601,workspace:{mode:"shared_team",shared_reports:true}}`。密码常量时间比较（可比较固定长度摘要），令牌至少32字节安全随机，固定1小时有效期，仅内存保存；进程重启失效。最多32个有效会话；满额429，不踢掉无关会话。
- 注销 POST `/api/workspace/logout`，Bearer必需，成功200 `{ok:true}`，只撤销当前令牌。过期、缺失、错误令牌均401，浏览器清内存并显示登录。
- 浏览器仅保存远端HTTPS URL；密码、Bearer、vendor key 均不进入 localStorage/sessionStorage/IndexedDB/URL/日志。刷新后重新登录。无需 Cookie，fetch 不带 credentials，令牌不通过 query 传输。
- 仅 Origin `https://saml1nhchen-ops.github.io` 可通过浏览器 CORS（Origin不含 /Money-coming 路径）。有 Origin 但不匹配（含null）一律403；无 Origin 仍需所有业务认证。OPTIONS仅验证Origin/允许方法/请求头并返回204，不访问业务、不返回token；允许 Content-Type、Authorization。响应 `Vary: Origin`、`Cache-Control:no-store`，不设 credentials/wildcard。
- Host必须与部署配置匹配（允许平台确需的内部健康检查host时只对healthz列明）。不信任客户端 Host、Origin、Forwarded/X-Forwarded-* 作为loopback请求参数，不关闭TLS验证。可信代理配置缺失时不得信任X-Forwarded-For实施限流。
- 登录尝试限制：每实际来源5次/15分钟、全局30次/15分钟，所有尝试计数；达到限制429并带Retry-After。锁与计数原子化；代理来源合并也采用严格上限，不通过伪造头绕过。密码请求上限4KiB，其他JSON请求上限256KiB；要求有效Content-Length，拒绝chunked/冲突长度、非JSON及非object载荷。网络读取有超时，并发连接上限防止慢连接绕过限流。
- GET `/healthz` 可匿名，仅200 `{ok:true}` 或503，不返回模型、任务、配置、secret或token。其他未列路径404；远端 `/api/geo/session`、全部 `/api/bai/*`、`/api/tools/*` 绝不公开。无匿名业务状态、公用token或浏览器配置vendor key接口。

## 3. 既有服务适配，不放宽保护

启动器负责原服务启动、runtime目录、重启中断恢复；使用本机pairing取得原服务token，bootstrap以本机认证POST bai/connect与profile注入服务器env密钥/固定配置。调用路径固定，不接收浏览器提交上游host/base_url/key。

网关→8772请求由服务器构造：固定 `http://127.0.0.1:8772`、固定loopback Host、无Origin或固定loopback Origin、Authorization为该服务的内部token。丢弃浏览器Host/Origin/Authorization/Cookie/Forwarded头，不转发浏览器Bearer到下游。本机session只由服务器调用，token绝不回传。下游401可重取内部token，但不自动重发可能收费的POST；返回失败供显式重试。

现有 website_inspection/fetch_website 的SSRF、公网IP、重定向、响应大小、TLS校验及所有本机Host/Origin保护保持。网关不能接受任意路径、重定向或HTTP CONNECT。

## 4. 模型目录与ready状态

仅用当前B.AI key实际 GET /models 的返回值；自动挑选固定GPT系列与Gemini系列各一个，排除auto/router/动态别名及无法确认厂商的ID，确定性排序并在本次进程内固定。优先服务端显式配置的完整ID；显式ID不在目录则报配置错误，不偷换。选择结果对前端显示完整model ID、协议、search=false、目录获取时间及“目录可见，尚未验证调用”。不伪造特定版本、费用或搜索能力。

最小默认协议chat；模型目录不能证明协议兼容，实际调用失败保留证据，禁止静默换模型/协议。US profiles固定市场US。最多选2个，GPT/Gemini各最多1个；generator必须为这两个profiles中已选的一个。

GET `/api/geo/state` 保留原 `{runner,busy,runs}`，追加：

```json
{"remote":{"mode":"shared_team","shared_reports":true,"ready":false,"reason":"missing_bai_key","limits":{"count":30,"max_models":2,"repeats":1}}}
```

`runner.profiles` 保留原 `{id,name,model,protocol,markets,search,provider,base_url,manufacturer}` 非密钥结构。ready表示已配置可选模型与运行依赖就绪，不表示真实付费调用成功。无key、目录失败、缺少GPT/Gemini之一、Node/tsx生成器缺失均ready=false；reason分别missing_bai_key/catalog_unavailable/required_models_unavailable/runtime_unavailable，可带安全中文说明。前端禁开始，展示可恢复状态；后台网络失败显示“后台连接失败”，不能把目录错误或未知状态渲染为0模型测评/0分。

## 5. 公开业务接口（全需Bearer）

|方法/路径|请求|成功响应/限制|
|---|---|---|
|GET /api/geo/state|无query|200，上述共享状态|
|POST /api/geo/inspect|`{website,market:"US"}`|200，保留现有website/brand/diagnosis/context/warnings；失败不造分数|
|POST /api/geo/plan|与start同模型/品牌输入|200，原plan结构；不调用付费模型|
|POST /api/geo/start|原start字段，固定market=US,count=30,repeats=1；providers 1–2个，generator为已选项；可有generate_only布尔|202，原job结构（id/status/config/plan）；生成最多3次，采样最多60次，总最多63次；generate_only=true仅3次生成|
|POST /api/geo/sample|原手工题输入，必须恰好30条有效且去重问题，每条≤4000字符；同模型/市场/repeats限制|202，原job；最多60次采样，必须再次显式开始|
|POST /api/geo/analyze|原`{id,brand_aliases?,skus?,competitors?}`|201，原job；仅对已有结果确定性重算，不付费调用|
|GET /api/geo/run?id=UUID|仅合法现有UUID|200，原job；全团队可读|
|GET /api/geo/export?id=UUID|同上|200，原job+raw_evidence；全团队可读，鉴权fetch下载不使用带token链接|
|POST /api/geo/stop|`{id:UUID}`|200 `{status:"stop_requested"}`；全团队可停|

不公开resume；重新执行必须由用户再次明确开始。query重复参数/未知参数拒绝；无query接口不得接受查询参数。载荷字段按现有schema白名单接受，不允许客户端注入configuration、plan、key、model快照或绕过预算的字段。

共享全局最多1个生成/采样任务，检查与入队原子化；冲突409。沿用原geo执行器GUARD/BUSY，网关不能仅做存在竞态的state预检查；不得部署多副本绕过锁。停止不保证撤销已提交请求，当前单次调用仍可能收费且证据保存。禁止自动retry/补题/换模型/页面恢复续跑/后台重启续跑；计划token数仅估算，价格和真实费用缺失为null。63次为调用数上界，不是固定金额上限。

每日预算采用保守预约：按准入时UTC日期，付费POST入队前一次性预约plan.maximum_calls（3/33/63或30/60），全团队共用默认126次/日；`generate_only`之后显式sample另预约60次。检查/扣除/落盘在网关同一锁内完成并先于下游付费POST；失败、停止、网络不明及重启均不自动退还，防止未知调用结果重试绕过。预算为当日准入任务的调用上界，跨午夜任务归准入日，不宣称实际逐日账单上限。计数落持久卷 `runtime/remote-budget.json`，原子替换；文件损坏/读写失败则fail closed返回503，不能归零继续。新UTC日可按新日期开始计数，旧记录保留；不提供公网重置接口。余额不足429 `daily_budget_exceeded`（说明次日或由运营者调整env，附重试时间）；state.remote追加 `budget:{date,limit,reserved,remaining}`。重启前后数值一致；这是调用数控制，不是金额封顶。

错误统一最少 `{error:string,code:string}`，可增加安全details；保留error为字符串兼容现有UI。400 invalid_request，401 unauthorized，403 origin_forbidden，404 not_found，409 busy，413 request_too_large，429 rate_limited，503 backend_unavailable/model_catalog_unavailable/runtime_unavailable，502 upstream_failed。不得透传secret或含上游请求头的异常。真实任务执行中的付费接口失败写入job/sample，报告保留partial/failed/unknown，不能写成“未提及”或成功。

## 6. 部署、持久化和回滚

根准备可迁移Docker及Render blueprint（付费单实例+持久盘）。镜像含锁定版本的Node/tsx/NiubiGEO生成代码与Python应用；运行数据/secret不COPY。runtime整体外置持久卷，至少保留geo-flows/bai-runs与生成器所需路径，避免挂载空卷遮住镜像内运行依赖：镜像只读依赖放独立路径或启动时从镜像种子复制到空卷的upstreams，再做就绪检查。不要把仅在开发机runtime存在的依赖误当镜像已包含。

非root进程，唯一外露PORT；健康检查只测网关/依赖进程是否可服务，不触发付费模型调用。SIGTERM让进程停止提交新调用、保存已有证据；重启将running/queued标记interrupted，不复跑。Render托管HTTPS；迁移阿里/腾讯用同一镜像、挂载卷、env及受信TLS反代。

回滚：停止公网入口/新任务，备份持久卷，在同一卷上切回上一镜像；确认不存在旧新实例同时消费。已有报告不可删除；secret轮换/进程重启使Bearer失效。无需数据库结构迁移；若实际新增持久格式，根先审查兼容与备份方案。

## 7. 验收与真实验证边界

本地可完成：假上游与HTTP回归、Docker构建/运行、静态secret扫描、持久卷重启、frontend交互、契约回归。假上游结果只能标合成验证，不能写成Cremo/GPT/Gemini实采。

关键验收：
1. 未登录及错误/过期token无法state/run/export/stop/inspect/plan/start/sample/analyze；同团队两令牌可互读互停；未知Origin拒绝，无Origin不免认证；OPTIONS不泄露任何token。
2. 公网无法获得本机session、B.AI connect/profile或native执行能力；Host/Origin注入不起效；原SSRF/TLS测试保持通过。
3. 弱口令启动失败、登录限流/体积限制/会话上限有效；并发start只有一个202，其余409；重启不恢复付费调用。
4. count31、repeats2、3模型、未知profile/generator、错市场、手工31题、resume均拒绝；30题2模型完整自动流程计划最多63次，手工最多60次，生成模式3次；失败不自动重试。
5. Pages正确Origin可登录连接；密码/token仅内存，URL可保存；刷新需重登；state未ready、空目录、后台断开、上游401/429等均有清楚状态，无假分数/假模型结果。
6. 镜像无secret/runtime数据、卷跨重启保留报告、生成器依赖可用；公网只开网关端口，部署配置显式单实例。

真实验证当前受阻：没有托管身份/授权/secret，B.AI保存绑定不存在。不能声称部署已上线、跨公网HTTPS实连、真实目录/协议/余额可用或Cremo US实采完成。根可先交付完整代码、镜像验证、部署蓝图与待填secret项；账号/secret/付费托管授权到位后再实际部署，并显式开始Cremo US（官网与品牌以现场核对为准）30题、真实GPT/Gemini固定ID、repeats1，保存真实run/export和失败证据；不购买或充值。
