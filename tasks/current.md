# 当前任务：AGENT-CONFIG-01

目标：将用户11个专业角色、五执行配置、S/M/L/R流程、按需调用和并发/上下文约束落到Codex与StarWork。
分支：agent-routing-policy。原网址功能在url-diagnosis-flow已推送7568c17，受控独立验收通过；历史见archive/2026-10-21-url-diagnosis.md。

验收标准：恰好5执行层、11个专业角色且无独立主控可解析；默认sol-low；子线程上限2；Sol高单例门禁；不继承完整聊天；职责/接口/数据库/交接规则明确；记录请求与观察值而不伪造实际调用；10任务校准从真实任务开始。
进度：11专业角色（无独立主控）、5层参数、路由、共享文档、CLI入口和离线门禁已实现，并经按luna-medium参数派发的独立静态验收及受影响范围复验通过；StarWork CLI确认11角色、0绑定，证据见docs/agent-policy-acceptance.json。实际模型核验仍受阻；证据见docs/agent-runtime-validation.md，Git由当前聊天串行提交。
阻塞：当前云端Codex CLI启动时只读文件系统失败，无法取得5档真实模型与思考深度日志；已有spawn请求返回未含实际模型元数据，不计验证通过。
外部待办：B.AI密钥SIGNAL_BAI_API_KEY尚未绑定，官网/API网络草稿未生效。需用户安全填写并保存发布；与本轮开发agent执行模型设置独立。
校准：尚无按新入口完成的真实业务任务；不把配置检查或启动探针计入10个任务。不承诺费用数据齐全。
