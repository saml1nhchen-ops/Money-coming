# Signal GEO 工作规则

先读本文件和 tasks/current.md；需要业务或模块背景时再读 docs/product.md、docs/architecture.md、docs/contracts.md。默认不读取历史任务、完整聊天和整个仓库。StarWork 角色/流程在 docs/agent-routing.md，机器映射在 .starwork/agent-policy.json。

## 执行与路由

当前聊天承担协调和普通开发，不定义或启动独立主控agent；产品只处理业务需求，协调职责不再转交一层。

- 仅使用 GPT-6.1 Sol、GPT-6 Luna。主控默认 sol-low；五份执行层在 .codex/agents/，11个专业角色引用它们，详见 docs/agent-routing.md。
- 主控能直接完成的普通任务直接做。S：Luna高实现→相关工具检查；M：Sol低实现→Luna中独立验收；L：必要时产品澄清→Sol高设计→前后端按文件范围实现→Luna中验收；R：Sol高设计→Sol低实现→Sol中独立验收→人工确认生产上线。
- 复杂度按业务影响和不确定性判断。产品仅业务标准不清时启动；架构仅复杂/重要设计时启动；角色完成即结束，不全部常驻。
- 默认仅主控活跃；主控加工作者最多3个，实现者最多2个，Sol高同时最多1个。子任务不再派生子任务。当前会话模型不能靠改文件切换。
- 当前聊天同时实现时也占一个实现者名额；两个专业实现者并行时，当前聊天只协调、不再并行改业务。CLI入口用--coordinator-implementing声明当前聊天正在实现。
- 原因/复现/范围均明确的Bug交Luna高；一次修复失败升Sol低。Sol低连续两轮无新增证据升Sol高。第二次调查必须改变方法；升级只交现象、复现、文件、事实、尝试结果和剩余假设。
- 子任务使用 fork_turns=none 和简短交接；不得默认继承完整聊天。长日志落文件，读相关片段。先相关验证，交付完成项目要求；返修只复验受影响部分。
- 原生Codex配置限制工作者线程数；跨进程并发/Sol高门禁与调用记录使用 scripts/agents/run.py。绕过该入口的其他客户端不受其进程门禁约束，不能声称全平台强制控制。

## 文件、数据与交付

- 业务代码为 dist/、tools/、server.py，不复制另一套应用。修改前明确文件归属、接口请求/响应/错误约定；主控串行处理Git，保留已有修改，不强推。
- 数据库建模、普通SQL、字段/索引/普通优化归后端；复杂建模、迁移、锁与事务归架构/复杂Bug。数据维护和清洗职责见角色表。
- 数据默认只读；全量计算交SQL/Python/工具，模型只看结构、统计、必要样本和异常。生产批量写入、删除、结构迁移先预览影响数、准备脚本/备份/回滚，待用户确认执行。
- 不把密钥写入聊天/仓库。unknown不当零；提及不等于推荐，普通链接不算AI原生引用；不编造模型、费用、验证或上线结果。
- 例行检查交脚本/定时工具；正常时无需模型，异常再调数据维护。本项目尚未部署定时维护。
- 每个独立功能一个主聊天，完成后更新tasks/current.md、必要decisions并归档详细过程。没有创建聊天工具时不伪造新会话。
- 验收读标准、diff和实现验证，再按需操作浏览器/数据库；输出“结论：通过/不通过；已验证事项；发现的问题；复现步骤；未完成验证”。验收不长期调查，问题退回实现者。
- 子任务交接：“任务ID；目标；必要背景；相关文件；允许修改范围；接口约束；验收标准；已知问题”。
- 实现完成返回：“完成情况；改动文件；验证命令与结果；未解决事项；需要主控处理事项”。

## 验证入口

- 路由/门禁：python scripts/checks/check_agents.py
- 调用审计：python scripts/agents/report.py
- 后端：python -m unittest discover -s tests -p 'test_*.py'
- 前端：node tests/test_frontend.cjs、test_diagnostic.cjs、test_report_summary.cjs、test_question_cards.cjs（均位于tests/）
- 实际浏览器：tests/browser_url_flow.py 和 tests/test_overlay_focus.cjs；依赖与合成边界见QUICKSTART.zh-CN.md。
- 调用日志缺少实际模型/深度时标unverified；配置值和模型自述不能代替执行证据。费用缺失为null，不猜价格。

StarWork既有交付保留在 _系统/协作/；旧岗位建制的“必须全流程/本轮只读”限制只适用于历史轮次，以本规则和当前用户授权为准。不要改身份/稳定偏好或晋升候选教训，除非用户授权。
