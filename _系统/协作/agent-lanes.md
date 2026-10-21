# 按需角色索引

当前聊天协调，不创建controller角色。11个专业角色共用5个执行层，定义不等于运行会话；current_session均保持unbound。

## Lanes

| lane | purpose | current_session | write_scope | worklog | workspace |
|---|---|---|---|---|---|
| product | sol-low：仅缺少业务目标、流程、范围或验收标准时启动产品。 | unbound | docs/product.md,tasks/current.md | lanes/product/worklog.md | lanes/product/workspace |
| architect | sol-high：L/R级跨模块架构、权限、复杂数据模型、迁移和关键技术决策。 | unbound | docs/architecture.md,docs/contracts.md,docs/decisions.md | lanes/architect/worklog.md | lanes/architect/workspace |
| frontend | sol-low：前端页面、交互、状态和接口；只改任务指定文件。 | unbound | dist/**,tests/*cjs | lanes/frontend/worklog.md | lanes/frontend/workspace |
| backend | sol-low：接口、业务、权限、建表/字段/索引和普通查询优化。 | unbound | server.py,tools/**,tests/test_*.py | lanes/backend/worklog.md | lanes/backend/workspace |
| simple_task | luna-high：文案、局部样式、明确规则的机械任务。 | unbound | task-assigned-files | lanes/simple_task/worklog.md | lanes/simple_task/workspace |
| simple_bug | luna-high：复现、原因、修复范围全部明确的简单Bug；一次失败升级Sol低。 | unbound | task-assigned-fix-files | lanes/simple_bug/worklog.md | lanes/simple_bug/workspace |
| complex_bug | sol-high：难复现、并发、性能、事务与一致性；定位根因和关键修复。 | unbound | task-assigned-cross-module-files | lanes/complex_bug/worklog.md | lanes/complex_bug/workspace |
| acceptance | luna-medium：常规独立验收：读标准/diff/验证，报告可复现问题，不做长期调查。 | unbound | acceptance-evidence-only | lanes/acceptance/worklog.md | lanes/acceptance/workspace |
| important_acceptance | sol-medium：权限、支付、生产迁移和核心一致性独立验收。 | unbound | important-acceptance-evidence-only | lanes/important_acceptance/worklog.md | lanes/important_acceptance/workspace |
| data_maintenance | luna-medium：只读查重、缺失值、核对、统计和异常报告；全量计算交工具。 | unbound | scripts/checks/**,scripts/data/** | lanes/data_maintenance/worklog.md | lanes/data_maintenance/workspace |
| data_repair | luna-high：按已确认规则生成清洗修复脚本；生产批量写入先备份回滚和人工确认。 | unbound | scripts/data/** | lanes/data_repair/worklog.md | lanes/data_repair/workspace |

模型/深度与职责映射：.starwork/agent-policy.json；任务级别、并发与数据边界：docs/agent-routing.md。旧四岗位日志保留作为历史，不作为当前活跃数。
