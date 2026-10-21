# 历史运行记录与当前策略

以下四岗位运行记录属于历史建制，不能作为当前角色数量或活跃进程数。当前角色定义见docs/agent-routing.md：当前聊天协调，11专业角色共用5层，按需启动；无独立主控。新策略的实际调用核验见docs/agent-runtime-validation.md，未核实项不声明通过。

# 当前任务内 Agent 运行记录

| 岗位 | 宿主返回的任务内 agent 标识 | 类型 | 持久桌面会话绑定 |
|---|---|---|---|
| product | /root/product | collaboration 子 agent | unbound |
| frontend | /root/frontend | collaboration 子 agent | unbound |
| backend | /root/backend | collaboration 子 agent | unbound |
| acceptance | /root/acceptance | collaboration 子 agent | unbound |

以上标识来自本轮 spawn_agent 返回值，只对当前任务的调度有效，不能当作 Codex App 的 thread UUID 或在其他机器复用。主协调者为 /root。

当前宿主没有 create_thread/send_message_to_thread，已进行工具发现；四个持久桌面会话状态为 manual_handoff_required，不伪造绑定。各岗位的完整可复制启动消息保存在 _系统/协作/lanes/<岗位>/launch.md。

仓库中的 .codex/config.toml 和 .codex/agents 提供可复用角色。已验证 TOML 与官方配置 schema；在其他客户端仍需同步分支、信任项目并具备相应自定义 agent 支持，不能据此声称已远程加载到用户电脑。

本轮子 agent 按同一项目文件共享事实，前后端交付后才进行最终验收；不是持续运行的后台服务，不会自动共享全部聊天记录。

## 本轮真实交接

- 产品已提交团队启动计划。
- 前端与后端分别完成接手说明，通过任务内 collaboration.send_message 回传产品及主协调。
- 主协调用 followup_task 激活产品，产品读取两侧文件并向验收发送正式建制验收指令。
- 主协调收到产品允许后用 followup_task 激活验收。
- 本段只记录当前任务内已发生的工具动作，不将其标记为 Codex App thread 投递。

## CLI 兼容性备注

StarWork alpha.25 对空 Cross-Lane Requests 表会回退到旧列格式，误把现代表头读成请求。shared.md 的空请求段改用说明文字以避免伪记录；后续 CLI 写入共享索引后应检查此段。岗位主记录在 agent-lanes.md；state.json 的空 lanes 表示尚无持久桌面绑定，并不代表四岗位未定义。

## 本轮完成情况

验收独立复跑了三组前端测试、两项语法检查和47项Python测试，检查五份角色TOML、业务范围和共享记录。清理伪请求后复核四岗位且零跨桌面请求；本轮团队建制通过，产品已读取证据并完成汇总。

不包含新增业务功能、真实付费模型或生产部署验收。最终文件见验收岗位的建制验收报告和产品岗位的团队交付摘要。所有常驻桌面会话仍unbound；本轮真正运行的是四个任务内子agent。
