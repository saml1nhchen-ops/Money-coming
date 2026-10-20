# 原生开源工具集成 v0.3

## B.AI 多模型聚合采样

运行 `start-bai.ps1`，打开 `http://127.0.0.1:8771/#/w/demo/bai`。该执行器独立于 8770 上的已有供应商会话，不读取、迁移或重启原 OpenAI/Gemini 会话。密钥只在 B.AI 进程内存中保存，不写文件。

连接调用官方 `GET https://api.b.ai/v1/models`，仅将该密钥返回的模型列为可选择项。用户为每个固定模型指定显示名称、Chat Completions / Responses / Messages 协议，以及中国/美国题集范围。Auto 不参与采样；支持联网的协议和模型可显式请求工具，DeepSeek 联网被拦截。账号模型列表可见不代表所选协议必定可用，仍需实际请求验证。

每个任务固定模型列表、题集、市场、协议和联网配置，最多 16 个模型 / 64 次调用。无自动重试、无模型替换。原始响应与 SHA-256、实际返回模型、usage、引用元数据、检索来源保存在 `runtime/bai-runs/`，可导出 JSON。主界面仅显示模型名称；调用渠道和协议在证据详情与导出中保留。提及分继续使用 `api-mention-v1`，不把失败/截断计为零，不把 API 数据标记为消费者 App 实测。

执行器没有订阅、充值、钱包或支付 API。调用按 B.AI 实际 Credits 规则计费；不承诺固定每条消息价格、固定优惠或 API 额度。没有 B.AI 密钥前，只有协议契约测试通过，不称为供应商实测。`tests/test_bai_service.py` 覆盖鉴权、来源与路径限制、密钥隔离、模型范围、按协议分派、多模型独立评分、错误与截断及不自动重试。

## 模型 API 采样（新增）

打开 `/#/w/demo/apis`。`ai_api.py` 提供 15 家官方模型服务的适配器，以及 OpenRouter 和自定义 OpenAI 兼容接口。平台、端点、协议、官方文档及消费者端区别在 `dist/ai-providers.json` 中明确登记；中国和美国独立配置题集、任务与结果。API 测量不混入虚构演示数据或消费者网页试测。

本机服务仅在内存保存手工配置的密钥，重启失效；不从父进程偷偷读取供应商凭据，不写浏览器 localStorage、源代码或证据文件。先配置 base URL、账户可用模型 ID（Perplexity 为 Agent preset）及密钥，再勾选平台提交题集。配置成功只证明校验通过，真实可用性需有凭据后运行；本次没有用户密钥，未完成供应商鉴权或付费实测。不同地域 / 业务空间的密钥必须对应其端点。

每次最多 64 个调用，每个平台逐题独立请求，无自动重试和跨供应商回退。接口统一限制输出 4096 token；如果输出被截断、被过滤、只有工具调用或为空，计为不完整，不参加提及分。联网工具已实现 OpenAI Responses、Gemini grounding、Claude web_search 和 Qwen enable_search；其余适配器当前为文本生成。请求联网不保证工具被执行；搜索执行证据另行记录。Perplexity 使用新的 `/v1/agent`，不新接已结束支持的 Sonar Chat Completions。

证据保存在忽略的 `runtime/ai-api-runs/<uuid>/`，含固定题集、市场、模型配置、每题原始响应、时间、返回模型、usage、完整性、引用元数据、独立检索来源和 SHA-256。已知凭据若意外出现在响应中会先脱敏，hash 对应保存后的证据文件。可下载完整 JSON 证据包；数据不上传公共站点。

`api-mention-v1` = 100 × 完整且未提示目标的回答中精确名称/别名命中数 ÷ 此类有效回答数。品牌与 SKU 分别计算；提示品牌的题不计入发现分，提示具体 SKU 的题不计入该 SKU 的发现分。英文使用词边界，中文使用明确别名子串；这只是可复核的词法提及，不判断推荐立场或事实准确性，别名质量需人工核对。有效样本数和完成覆盖率必须伴随分数；无有效样本显示空值，不把失败当零。该分数不声称代表全市场曝光率、推荐排名或 App 表现。

验证：`python -m unittest discover -s tests -p test_ai_api.py` 覆盖 17 个入口的请求协议、四类原生搜索参数、主要响应结构、截断/过滤、品牌与 SKU 分母、无凭据前置拦截、鉴权失败和证据脱敏。使用本地契约响应进行验证，不称为供应商实测。

## 当前交付与边界

18 个真实 GitHub 仓库已下载到 `runtime/upstreams/`，完整保留各自许可证与提交历史。`upstreams.lock.json` 固定每个仓库的准确提交；`dist/upstreams.json` 包含 420 份原始 SKILL.md 文档、原文 hash、许可证和原仓库链接。它们不是重写的摘要，也没有安装到用户全局 Skill 目录。

原生执行器位于 `native_service.py`，仅绑定 `127.0.0.1:8770`。网页从已声明的操作构造参数数组，不执行网页提交的任意 shell。每个任务独立保存原生文件、stdout、stderr、退出码、来源版本和文件 hash。

| 上游 | 已实现的执行方式 | 仍需用户/环境提供 |
|---|---|---|
| NiubiGEO | 原生 TypeScript CLI audit；已安装依赖并检查 CLI | OpenRouter 密钥、模型和审核后的问题；未做付费实测 |
| Potato | 原生 validate、estimate、mock、anthropic run | 实测需审核后的 brands.yml / questions.yml 与 Anthropic 密钥；mock 明确为合成演示 |
| OpenSEO | 原始 Skill + MCP initialize/list/call 适配器 | 已部署的 OpenSEO MCP 地址及凭据；完整应用未启动 |
| Elmo | 原始 Skill + MCP initialize/list/call 适配器 | Elmo 服务和认证；完整应用未启动 |
| Yao GEO | 原生 DeepSeek 结果分析脚本 + 全部原始 Skill | 实时采集需 OpenCLI/浏览器桥接或 Android/Appium 与平台登录；本轮未运行消费者采集 |
| Crawl4AI | 原生 HTTP 策略，导出 HTML、Markdown、完整结果 JSON | JS 渲染和登录浏览器不在本轮 HTTP 适配器内 |
| Claude SEO | 原生 fetch_page.py + 原始 Skill | 高级 Google/DataForSEO 功能需对应账号与配置 |
| Auriti | 原生 geo audit，原生 JSON 报告 | 重要业务判断仍需复核；原生分数不换算为 Signal 分数 |
| Onvoyage GTM | 原始 Skill + 模型执行 | OpenRouter 模型与任务材料；模型执行没有浏览器、终端或 MCP 工具 |
| SE Ranking | 原始 Skill + MCP initialize/list/call | SE Ranking 账号、服务认证；尚未完成 OAuth 或实测 |
| Marketing Skills | 原始 Skill + 模型执行 | 模型密钥与任务材料；不包含宿主代理的外部工具能力 |
| Aaron Marketing | 原始 Skill + 模型执行 | 同上；保留上游 Skill 的数据缺失边界 |
| Claude Blog | 原生 analyze_blog.py + 原始 Skill | 模型写作需密钥；Google/CMS 功能未接入 |
| NotFair | 原始 Skill + 模型执行 | 模型密钥与任务材料；没有把整套 Claude 插件运行时搬入网页 |
| Promptfoo | 原生 eval，对已保存回答运行 contains 断言 | 无模型调用；该操作是离线回归，不是新采样 |
| BeyondSEO | 原生 crawl，限制默认 1 页、最多 15 页 | 浏览器渲染/远程发布不在该操作内 |
| OneGlanse | 完整源码固定、服务连通检查 | Docker、PostgreSQL/ClickHouse/Redis、平台登录；完整应用未启动 |
| Voyage GEO Agent | 原生 CLI；单提供方、默认 1 问、最多 8 问 | OpenRouter 密钥及明确处理模型；未做付费实测 |

“导入全部源码/Skill”不等于“全部原生平台功能已上线”。尤其 Elmo、OpenSEO、OneGlanse 的完整应用栈、浏览器采样以及供应商认证仍缺运行环境；MCP 适配器没有假定服务已部署或认证已通过。

## 使用

运行项目根目录 `start-tools.ps1`，打开 `http://127.0.0.1:8770/#/w/demo/tools`。本机网页自动取得当前执行服务的会话令牌。服务重启后令牌失效。线上网页可手工连接该执行器，但浏览器可能要求本地网络访问授权；本机页面不依赖该跨站连接。

密钥在运行弹窗填写，只用于本次请求；执行器不把它们写入配置或源码。来自父进程的 API_KEY / TOKEN / SECRET / PASSWORD 环境变量不自动传给上游，仅注入本次显式填写的供应商密钥。任务目录和所有虚拟环境均被 Git 忽略；可能包含客户材料的任务产物不要上传公共站点。

原生分数原样保留，不冒充设计方案的六维准备度。成功任务可以“将原生输出载入证据附录”；该操作只建立带 hash 的输出证据，未按 Signal rubric 核验的规则保持 unknown，不自动生成曝光率或提升结论。

## 安装与复现

1. `python tools/sync_upstreams.py`：按锁定提交恢复全部上游仓库。通过 `SIGNAL_GIT` 可指定 Git 可执行文件。
2. `python tools/install_runtimes.py`：为七个 Python 项目建立独立环境。可传入单个项目 ID 重试。Windows 长路径安装失败时，可将 `SIGNAL_SHORT_RUNTIMES` 指向当前工作区内较短的目录；实际解释器路径保存在忽略的 `runtime/installed.json`。
3. 在 `runtime/upstreams/niubigeo` 安装其 Node 依赖。Promptfoo 使用与源码 package.json 对应的 `promptfoo@0.124.1` 正式包；不是把 TypeScript 仓库直接当已编译程序运行。
4. `python tools/build_catalog.py` 从真实已下载文件生成在线目录。
5. `python tools/smoke_native.py` 执行无付费模型调用的适配器冒烟验证。会访问 example.com，并运行明确标记的离线/合成 fixture。

`python -m unittest discover -s tests -p test_native_service.py` 检查令牌、来源限制、文件边界及许可证；前端回归沿用 `test_frontend.cjs` 和 `test_diagnostic.cjs`。

## 部署的作用

本机执行时电脑和服务要保持运行。部署到可持续运行 Python/Docker 的服务器后，可从其他设备访问、集中保存证据、定时采样和多人使用。当前 Sites 仍是静态公开前端，不能运行这些长驻进程；本轮没有配置云主机或向网站上传客户任务数据。

## 自动诊断流程（8772）

`start-signal.ps1` 复用已运行的 8770 / 8771 并启动 8772，保留现有密钥会话。电脑重启后需要在原接口页面重新配置密钥，凭据不写入源码或本地存储。在线站点的“自动诊断与竞品分析”入口打开本机执行器。

中国与美国分别保存官网、精确别名、SKU、竞品、题目、模型和运行记录。官网抓取只用于生成背景；无正文或被拒绝时允许显式使用用户补充背景，抓取失败保留在报告。抓取检查公开地址、重定向、类型和大小，禁止内网地址。

`tools/niubi_bridge.mts` 直接导入已固定提交的 NiubiGEO `PromptGenerator.buildGenerationPrompt` 和 `parseGeneratedPrompts`；不把手工模板标成上游生成。候选题不具有真实使用量。官网完整摘录和 hash 留在本机，生成上下文按已有接口限制截取到 3900 字符内。一次生成失败不进入回答采样，也不自动重试。支持仅生成、审核编辑题目后再采样。

询问模型复用 8771 的 B.AI 或 8770 已配置厂商直连，不复制 API 密钥；每次单题调用，最多 64 次回答，加 1 次生成，重复次数 1–3。停止任务后不再提交新调用，当前请求的证据仍保存。重启后在途任务标为 interrupted，禁止静默重跑。

`tools/geo_analysis.py` 为 Signal GEO 的确定性分析层，不冒称 NiubiGEO 原生评分。完整回答中按精确别名计算提及率；题目点名任何跟踪品牌、竞品或 SKU 时排除自然发现分母。失败和截断不算零分。明确编号列表位置和原文证据单独保留；无序提及不生成排名，不推断情感或全市场排名。SKU 分数及明确列表位置单独计算。

引用分析区分 provider citations、retrieved sources、answer links。只有平台引用元数据进入品牌引用指标；普通 URL 不自动证明引用或联网。竞品缺口要求本条有效自然发现回答中竞品被提及或被引用、自有品牌既未被提及也未被引用。原始响应、用量、时间、模型、联网条件、hash、生成记录、抓取背景、分析规则均可导出。

任务存在 Git 忽略的 `runtime/geo-flows`，不随公开站点发布。单元测试包含真实上游出题/解析调用，模型采样测试使用合成 fixture；外部实测另存为真实 run，不把离线测试当成模型测量。


## 30 题厂商基线（2026-10-20）

按用户最终口径：每市场默认 30 道不同问题，每题只问一次，每厂商选择一个固定模型。同一市场各厂商使用完全相同的冻结题库，保存题库 SHA256。中国、美国仍分别配置和运行。默认题型计划为自然发现 21、品牌认知 5、比较 4；按实际题目是否点名跟踪对象重新判定题型，报告分开出分，不混入自然发现分母。

生成器每次最多生成 10 题，30 题拆为 3 次调用，使用不同需求侧重点和已有题目上下文；对大小写、空白、标点规范化去重。不同措辞的语义重复不宣称已彻底消除，仍可人工审核。题数不足时保留现有题库，不自动补题或直接采样。支持用户导入最多 300 道不同题目；新任务拒绝重复采样参数，旧报告保持原始参数。

厂商归类基于固定模型 ID；直连与 B.AI 的同厂商模型共用一组选项，后端也拒绝同厂商重复选择。调用计划为题数 × 厂商数，再加出题批次；查看计划不发起生成。回答逐题执行，逻辑批次不超过 64 条，单次底层请求仍只有一道题。遇到 400/401/403/404/429 等权限、额度或配置错误时，停止该模型后续调用，其他模型可以继续。未调用项不会伪装成失败回答或零分。

长任务可显式继续未完成题目，先核对原提交 runner_id 的执行状态并回收证据；已尝试题目不自动重跑，尚在执行的调用不重复提交。继续前验证冻结题库和原模型配置。题库覆盖页展示不同问题数、实际题型、需求维度与调用完成度；所有新逻辑的测试使用离线 fixture，不冒充 30 题真实测量。
