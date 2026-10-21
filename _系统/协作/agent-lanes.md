# Agent Lanes

## Lanes

| lane | purpose | current_session | write_scope | worklog | workspace |
|---|---|---|---|---|---|
| product | 产品规划与领导：拆解需求、确定验收标准、协调前后端、接收验收反馈 | unbound | _系统/上下文/**,_系统/任务/**,_系统/协作/lanes/product/** | lanes/product/worklog.md | lanes/product/workspace |
| frontend | 前端设计与实现：界面、交互、响应式与证据展开 | unbound | dist/**,tests/test_*.cjs,_系统/协作/lanes/frontend/** | lanes/frontend/worklog.md | lanes/frontend/workspace |
| backend | 后端实现：接口、数据、分析规则与服务运行 | unbound | server.py,tools/**,tests/test_*.py,_系统/协作/lanes/backend/** | lanes/backend/worklog.md | lanes/backend/workspace |
| acceptance | 独立验收：等待前后端交付，复现问题、验证证据并反馈，禁止自行宣称发布 | unbound | _系统/协作/lanes/acceptance/** | lanes/acceptance/worklog.md | lanes/acceptance/workspace |
