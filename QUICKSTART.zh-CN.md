# 当前版本快速开始（2026-10-21）

这是 Signal GEO 当前完整应用源码快照，包含最新的三步品牌分析界面、Python 本机服务、模型接口适配、问题生成、回答排名、SKU/竞品与引用分析，以及测试和固定版本的开源集成清单。

## 本机启动

需要 Python 3.11+、Node.js 和 Git。Windows 在源码根目录执行 `powershell -ExecutionPolicy Bypass -File .\start-signal.ps1`，然后打开 http://127.0.0.1:8772/#/w/demo/research 。API 密钥需要在本机网页重新配置，不包含在此仓库中。

自动生成问题依赖固定版本 NiubiGEO：先运行 `python tools/sync_upstreams.py` 下载锁定的开源仓库，再运行 `python tools/install_runtimes.py` 安装相应依赖。该安装过程需要网络，第三方工具有各自的环境要求，详见 tools/INTEGRATION.md。

macOS/Linux 也可在项目根目录分别开终端运行 `python3 tools/native_service.py`（官方 API，8770）、`python3 tools/bai_service.py`（聚合服务，8771）、`python3 tools/geo_flow.py`（自动诊断，8772）。仅检查网页时只需最后一个服务；模型采样还需运行你使用的连接服务。浏览器打开 http://127.0.0.1:8772/#/w/demo/research ，保持对应终端运行。

每市场默认 30 道不同问题，每题每模型一次，每厂商固定一个模型。模型调用按供应商规则计费，导出源码本身不触发模型请求。

## 从网址到逐题报告

1. 选择目标市场，填写官网网址，点击“读取官网并诊断”。这一步不调用模型；检查当前页面的标题、描述、主标题和可读正文，展示抓取记录与建议。
2. 核对自动识别的品牌；依据不足的候选需要确认，也可修改品牌和补充精确别名、产品、竞品。网页准备度只表示这四项基础检查，不代表完整六维 GEO 评分或 AI 表现；正文不足或结构不可观察时不生成总分。
3. 选择已配置的模型，点击“开始分析”。程序读取官网背景，分三批生成 30 道不同问题，随后询问所有所选模型。未配置模型时仍可完成第 1 步。连接在本机 8770 官方 API 或 8771 聚合服务管理，不从旧聊天或 GitHub 恢复密钥。
4. 报告先展示提及得分和结论，再展示逐题卡片、竞品差距、引用与行动。点击任一问题打开弹窗，核对所有所选模型的原文、品牌提及、竞品、明确列表位置及引用。自然发现题与点名品牌/比较题分开计分；普通回答链接不算 AI 原生引用。失败、截断和未运行不会算作零分。

模型配置和运行记录属于启动这些服务的机器。静态预览不运行 Python 后台；推送此分支不会自动更新原 Sites。

## 可重复的受控浏览器联调

安装 Python Playwright 与 Chromium 后，在一个终端运行 `python tests/fixtures/serve_url_flow.py --partial`，另一个终端运行 `python tests/browser_url_flow.py`。固定占用本机 8772，运行前停止正常诊断服务。测试使用临时目录和合成官网/模型响应，仅替换出站传输；保留实际 HTTP 路由、HTML 解析、固定版本出题解析、任务与报告流程。它不会连接真实模型或证明 Cremo 的真实表现。截图和摘要默认写入 `/tmp/geo-url-flow-evidence`，不提交运行样本。

共享弹窗的键盘回归可另运行 `node tests/test_overlay_focus.cjs`，同样需要 Python Playwright 和 `/usr/bin/chromium`，无需启动服务或连接模型。

## 导出范围

包含应用源文件、前端静态资源、测试、启动脚本、上游版本锁、原始 Skill/许可证目录数据与 Sites 配置。额外提供本说明及导出清单。保留原始 README.md 作为历史说明，其中早期版本的功能描述以当前代码和本说明为准。

未包含旧 Git 历史、API 密钥、凭据、浏览器会话、本机任务/回答/证据、数据库、日志、进程文件、依赖缓存及 runtime 中的第三方克隆和已安装依赖。第三方源码可通过 tools/upstreams.lock.json 和同步脚本恢复；本仓库不是包含依赖的离线运行镜像。dist/upstreams.json 内保留原始公开文档和许可证。

验证：`python -m unittest discover -s tests -p "test_*.py"`、`node tests/test_frontend.cjs`、`node tests/test_diagnostic.cjs`。这些回归测试不需要真实付费采样。
