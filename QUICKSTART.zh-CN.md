# 当前版本快速开始（2026-10-20）

这是 Signal GEO 当前完整应用源码快照，包含最新的三步品牌分析界面、Python 本机服务、模型接口适配、问题生成、回答排名、SKU/竞品与引用分析，以及测试和固定版本的开源集成清单。

## 本机启动

需要 Python 3.10+、Node.js 和 Git。Windows 在源码根目录执行 `powershell -ExecutionPolicy Bypass -File .\start-signal.ps1`，然后打开 http://127.0.0.1:8772/ 。API 密钥需要在本机网页重新配置，不包含在此仓库中。

自动生成问题依赖固定版本 NiubiGEO：先运行 `python tools/sync_upstreams.py` 下载锁定的开源仓库，再运行 `python tools/install_runtimes.py` 安装相应依赖。该安装过程需要网络，第三方工具有各自的环境要求，详见 tools/INTEGRATION.md。

每市场默认 30 道不同问题，每题每模型一次，每厂商固定一个模型。模型调用按供应商规则计费，导出源码本身不触发模型请求。

## 导出范围

包含全部 46 个应用源文件、前端静态资源、测试、启动脚本、上游版本锁、原始 Skill/许可证目录数据与 Sites 配置。额外提供本说明及导出清单。保留原始 README.md 作为历史说明，其中早期版本的功能描述以当前代码和本说明为准。

未包含旧 Git 历史、API 密钥、凭据、浏览器会话、本机任务/回答/证据、数据库、日志、进程文件、依赖缓存及 runtime 中的第三方克隆和已安装依赖。第三方源码可通过 tools/upstreams.lock.json 和同步脚本恢复；本仓库不是包含依赖的离线运行镜像。dist/upstreams.json 内保留原始公开文档和许可证。

验证：`python -m unittest discover -s tests -p "test_*.py"`、`node tests/test_frontend.cjs`、`node tests/test_diagnostic.cjs`。这些回归测试不需要真实付费采样。


### 多供应商采样

统一注册表为 `dist/ai-providers.json`，由 `tools/model_providers.py` 读取；
认证的 `/api/tools/ai/providers` 返回公开配置状态，绝不返回密钥。
支持 OpenAI Responses、Anthropic Messages、Gemini generateContent，以及
Perplexity Sonar、DeepSeek、Qwen、智谱、Kimi、豆包、MiniMax、混元的 Chat Completions。
B.AI 保留原有目录和连接流程，也可作为可选环境配置供应商。

复制 `.env.example`，仅填写需要使用的 `SIGNAL_<P>_API_KEY`。
每个供应商支持 `SIGNAL_<P>_MODEL` 和 `SIGNAL_<P>_BASE_URL` 覆盖。
豆包必须填写 `SIGNAL_DOUBAO_MODEL`（模型 ID 或 ep- 接入点），否则显示未配置。
Compose 将这些变量传给后端；重启服务后生效。缺失密钥的供应商显示
“not configured”并跳过，不产生模拟回答或分数。采样设置按美国、中国分组，
可以选择多个已配置供应商并编辑本次模型 ID；市场语言仍由任务市场决定。
直连 API 未提供 providers 时采样全部已配置供应商，也可传 providers 子集和
models（provider ID 到模型 ID 的映射）。模型 API 的观察不代表消费者 App 的表现。

离线验证：`python3 -m unittest discover -s tests -p 'test_model_providers.py'`。


### Shared provider routes / 共享路由

Each provider uses `SIGNAL_<P>_ROUTE=auto|official|openrouter|nvidia_nim|siliconflow`
(default `auto`; only routes listed below are supported for each provider).
Auto chooses a configured official free tier first, then the first configured free
aggregator in table order, then a configured paid official route. It resolves before
the request; errors do not trigger retries or route switching. Missing credentials or
Doubao's missing model leave that route unconfigured. Explicit routes never fall back.
OpenAI, Anthropic and Perplexity use official paid accounts only.

| Provider | Official default / cost | Free alternate routes (priority order) |
| --- | --- | --- |
| OpenAI | `gpt-5` / paid | — |
| Anthropic | `claude-sonnet-4-5` / paid | — |
| Gemini | `gemini-3.5-flash` / Google AI Studio free tier | — |
| Perplexity | `sonar` / paid; no free API | — |
| Zhipu | `glm-4.7-flash` / free; paid override `glm-4.6` | siliconflow: `THUDM/GLM-4-9B-0414` |
| DeepSeek | `deepseek-chat` / paid, low cost | nvidia_nim: `deepseek-ai/deepseek-v4-flash` |
| Qwen | `qwen-plus` / paid, new-user credits | siliconflow: `Qwen/Qwen3-8B`; nvidia_nim: `qwen/qwen3-next-80b-a3b-instruct` |
| Kimi | `kimi-k2-0905-preview` / paid, trial credits | nvidia_nim: `moonshotai/kimi-k2-instruct` (**unverified**) |
| MiniMax | `MiniMax-M2` / paid | openrouter: `minimax/minimax-m2.7:free`; nvidia_nim: `minimaxai/minimax-m2.7` |
| Doubao | Ark only / paid, trial credits; requires `SIGNAL_DOUBAO_MODEL` | — |
| Hunyuan | `hunyuan-lite` / historically free, new-user tokens; paid override `hunyuan-turbos-latest` | — |

Shared keys (one key serves all applicable providers):

| Route | Base URL | Shared key | Free conditions / reference limits |
| --- | --- | --- | --- |
| openrouter | `https://openrouter.ai/api/v1` | `SIGNAL_OPENROUTER_API_KEY` | Free model IDs end in `:free`; reference quota 50 requests/day |
| nvidia_nim | `https://integrate.api.nvidia.com/v1` | `SIGNAL_NVIDIA_API_KEY` | Free prototyping; approximately 40 RPM |
| siliconflow | `https://api.siliconflow.cn/v1` | `SIGNAL_SILICONFLOW_API_KEY` | Free models require real-name verification |

These are configured defaults and reference limits, not live account verification.
Model IDs, availability, pricing and quotas change frequently; check the service
console before use. Free describes the listed route/model tier, not guaranteed
account entitlement or unlimited usage. Trial credits count as paid routes.
All supplied routes are marked as not live-tested in registry metadata.

Override models with `SIGNAL_<P>_<ROUTE>_MODEL`, uppercasing both names, e.g.
`SIGNAL_QWEN_NVIDIA_NIM_MODEL` or `SIGNAL_ZHIPU_OFFICIAL_MODEL`.
Official routes also accept legacy `SIGNAL_<P>_MODEL` (route-specific wins) and
`SIGNAL_<P>_BASE_URL`; aggregator endpoints remain fixed so shared credentials go
to the declared gateway. Model overrides on official free routes are conservatively
marked paid unless they match the free default. Set `ROUTE=official` to select a
paid override even when a free alternate is configured. OpenRouter overrides must
end in `:free` to retain free status. NVIDIA prototype overrides retain the prototype
free tier; other unknown model overrides are conservatively marked paid.

The expandable sampling settings show the resolved route and free/paid flag,
allow route selection, and reset the model field to the selected route default.
Status and exported evidence include route metadata; credentials remain server-side.
Route selection does not claim that model API results represent consumer apps.
