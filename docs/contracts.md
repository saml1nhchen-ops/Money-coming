# 当前接口摘要

8772使用本机同源session配对和Bearer鉴权；校验Host/Origin，不把loopback开发接口称为生产多用户服务。

- POST /api/geo/inspect：请求website、market(CN/US)；响应website抓取记录、brand候选/来源/needs_confirmation、diagnosis(scope=website_readiness、score可null、checks、methodology)、context、warnings。无需模型，抓取失败返回错误而不是零分。
- POST /api/geo/start：官网、品牌别名、市场、固定模型providers/generator、30题默认范围和可选SKU/竞品/背景；返回任务，后续GET /api/geo/run?id=...轮询。
- job.prompts是逐题全集；question_index+provider+repeat关联样本。config.configuration保存非密钥模型快照。report.samples保留analysis；失败、未运行、截断不记未提及。
- citation、retrieved_source、answer_link分开；只有平台返回citation计原生引用。brand/comparison题排除自然发现分母。
- 8771 /api/bai/connect、/profile仅现有服务连接与固定模型配置，不自动购买/充值。

跨模块变更前主控在本文件或模块附录明确字段、错误语义和兼容策略，先定契约再并行。不在摘要复制全部schema。
