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
