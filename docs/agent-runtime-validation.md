# AGENT-CONFIG-01 验证记录

2026-10-21，分支agent-routing-policy。当前聊天协调，不定义独立controller；11专业角色、5执行层。

## 已验证

- python scripts/checks/check_agents.py：五层、十一角色、无controller、工作者上限、Sol高单例、当前聊天占用实现者名额、配置与模型自述不能当实际元数据等检查通过。
- .codex/config.toml与五个层文件经tomllib及官方缓存schema（/tmp/codex-agent-config-schema.json）校验通过。
- CLI命令dry-run覆盖五档，只表示正确传入model和model_reasoning_effort，不表示实际执行。
- 按luna-medium参数派发的独立验收读取diff、实现验证和脚本（宿主未回传实际模型/深度），静态/门禁通过；新增当前聊天实现者计数后仅做该范围复验，通过。原始验收摘要在本机/tmp/geo-routing-acceptance.json，非跨机器持久日志。
- StarWork CLI实际识别11个lane、0绑定；各角色启动说明/日志/工作目录齐全，独立定向复验通过。
- 未改dist、tools、server.py或数据库，不把无关业务测试重复运行当配置验证。

## 实际运行受阻

本机codex-cli 0.159.2。首次用ephemeral/json/strict-config、gpt-6-luna/medium和只读沙箱执行仅回复OK的探针，在模型调用前失败：failed to initialize in-process app-server client: Read-only file system (os error 30)。

第二次改变方法：使用官方schema支持的sqlite_home与log_dir指向ignored runtime可写目录，并加no-daemon；仍在相同初始化阶段失败。没有改CODEX_HOME、绕过沙箱或读取/复制认证凭据。

两个真实探针的stdout/stderr和摘要仅保存在ignored runtime/agent-execution/bootstrap-probe-{1,2}。已记录请求luna-medium，实际模型与深度观察值为空、actual_model_verified=false、engine_exit_code=1。不重复启动其余四档消耗无效调用。

| 执行层 | 参数校验 | 实际模型/深度 |
|---|---|---|
| sol-low | 通过 | 未验证 |
| sol-medium | 通过 | 未验证 |
| sol-high | 通过 | 未验证 |
| luna-medium | 通过 | CLI初始化受阻，未获得模型日志 |
| luna-high | 通过 | 未验证 |

宿主collaboration工具接受过Luna高的只读检查、Luna中的独立验收请求，但返回没有实际模型/深度元数据，因此不能以请求参数、角色名称或模型自述补齐核验。

## 后续

在能正常启动Codex且提供可信运行元数据的客户端，显式运行python scripts/checks/check_agent_runtime.py --all。它可能消耗少量模型token，首次引擎失败或缺少元数据即停止，不执行五次相同无效重试。入口不采信assistant文本中的模型自述；CLI若不提供模型/深度metadata仍为unverified，需要对应宿主日志适配，不能宣布通过。

十个真实业务任务校准尚未开始：report.py当前显示0个任务，两个启动检查被排除，实际费用null。此结论不等于五档实际模型调用已验证，也不等于配置已热加载到用户电脑。
