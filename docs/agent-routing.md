# 11个专业角色、五执行配置

当前聊天负责协调，默认gpt-6.1-sol/low，不在角色列表另设controller；产品负责用户目标/流程/标准。协调不新增模型调用。

模型及深度的唯一五份执行层在 .codex/agents/{sol-low,sol-medium,sol-high,luna-medium,luna-high}.toml；.codex/config.toml 的角色入口引用这些文件，.starwork/agent-policy.json 记录路由。职责与执行参数分开，不为11个专业角色复制环境。

| 角色入口 | 执行层 | 负责人范围 |
|---|---|---|
| product | sol-low | 缺失的业务目标、流程、范围、异常、验收 |
| architect | sol-high | 跨模块、复杂模型、权限、迁移、关键决策 |
| frontend | sol-low | 页面、交互、状态、接口接入 |
| backend | sol-low | API、业务、数据库建模/普通查询优化、权限实现 |
| simple_task | luna-high | 文案、局部样式、机械修改 |
| simple_bug | luna-high | 已明确复现/原因/修复范围的Bug |
| complex_bug | sol-high | 难复现、并发、性能、锁/事务/一致性 |
| acceptance | luna-medium | 常规独立验收，反馈后结束 |
| important_acceptance | sol-medium | 权限、支付、迁移、核心一致性验收 |
| data_maintenance | luna-medium | 只读数据质量、查重、核对、统计和异常 |
| data_repair | luna-high | 明确规则的清洗修复脚本 |

sol-* = gpt-6.1-sol；luna-* = gpt-6-luna。深度由low/medium/high决定。不使用其他模型。

## 分级与按需调用

S目标明确、不改API/表结构：Luna高实现、工具检查、主控汇总，无产品/架构/独立验收。
M单模块页面/API：Sol低实现，Luna中验收。
L跨模块或设计不确定：业务标准不清才调用产品；Sol高设计后前后端可并行，Luna中验收。
R权限/支付/生产迁移/核心一致性：Sol高设计，Sol低实现，Sol中独立验收，生产上线人工确认。

产品输出目标/用户流程/范围/异常/验收标准；架构输出边界/接口/数据变化/步骤/验证/风险回滚。前后端并行前锁定接口约定，文件修改范围互斥。普通任务由主控直接做，避免无价值转交。

Bug：Luna高一次失败升Sol低；原因不明普通Bug直接Sol低；Sol低两轮无新增复现/范围/假设排除等证据升Sol高。验收只验证和反馈，不接长期调查。

## 使用与实际验证

- 支持自定义角色且信任项目的Codex客户端可加载11个专业角色；五个共享层是真实model/model_reasoning_effort参数，角色描述不是模型切换器。
- 本机CLI入口：python scripts/agents/run.py --role frontend --task-id TASK-01 --brief tasks/brief.md。
- 加 --dry-run 只解析命令，不调用模型、不证明运行配置生效。升级选择对应role；例如architect/complex_bug映射sol-high，不能把backend强行配成其他层。
- 入口显式传Codex的-m和model_reasoning_effort，并关闭子任务再派生。这里不用codex -p：当前CLI该参数加载用户目录profile文件，不能假设它读取项目中的五层。
- 原生配置的max_concurrent_threads_per_session=2计算子线程；加主控共3。入口用SQLite事务保留最多2工作者槽位，同一入口的Sol高最多1（含声明的主控档位）。主控升级高档需传--coordinator-profile sol-high；其他客户端/人工直接启动的会话不在该跨进程门禁内，需调度者同样遵守。
- 默认fork_turns=none，不带完整历史；简报上限12000字符，提供必要摘要与路径，不回贴大段代码。原生客户端角色调用不能由此保证实际不继承历史，派发时必须显式选择。
- 当前聊天正在写实现时传--coordinator-implementing，它也占实现者槽；两个专业实现者并行时当前聊天仅协调。档位和是否正在实现由调用者声明，入口不能观察其他客户端的实际状态。
- 调用事件和摘要仅落ignored runtime/agent-execution，不把完整聊天或密钥提交Git。仅运行器metadata记录的模型和深度能匹配验证；assistant自述/配置回显不算。缺metadata即unverified，退出码3；引擎失败保留原exit，不能当执行成功。
- 运行器报告的是runtime metadata，不保证供应商内部模型实现。当前云端CLI实探遇只读文件系统，尚不能完成五档真实调用核验；宿主spawn接受过Luna高请求，但没有返回实际模型/深度证据。两者不计通过，也不算真实业务校准。
- 此文件无法热切换已经运行的主控模型。新会话载入配置后仍须核对实际日志。

## 十个真实任务校准

运行python scripts/agents/report.py，逐任务记录实际usage/账单费用、同任务同角色重试与显式--rework标记。校准目标10个真实任务；启动检查、配置检查、mock测试不计。费用未知保留null；重试次数不是账单调用次数；返工率依据显式标记，漏记不能视为零。没有供应商账单不能承诺已知实际费用。

正常例行数据检查仅用scripts/checks或scripts/data工具，异常再调用模型。当前未部署定时器或生产数据维护任务。
