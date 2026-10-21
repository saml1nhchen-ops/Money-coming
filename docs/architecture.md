# 架构摘要

- dist/：无需构建的浏览器界面；research-ui.js/website-inspect.js/question-cards.js/report-summary.js实现主流程。
- tools/geo_flow.py：8772自动诊断，读取网站、固定NiubiGEO生成解析、模型采样、确定性分析；结果在ignored runtime/geo-flows。
- tools/bai_service.py：8771 B.AI聚合连接，凭据与模型配置在服务内存；tools/native_service.py+ai_api.py：8770独立API适配。
- server.py：8765旧工作台，SQLite状态在ignored work/signal.db。当前不是PostgreSQL/MySQL生产部署。
- NiubiGEO固定版本见tools/upstreams.lock.json，依赖在ignored runtime/upstreams。
- 开发角色使用Codex的Sol/Luna执行层；B.AI是被测分析模型通道，两种配置不得混淆。
- 当前云端启动与依赖步骤保存于环境配置；本机通用入口见QUICKSTART.zh-CN.md。进程不会因保存Git配置自动常驻。
