<!-- STARWORK:MULTIAGENT_MESSAGE v1 -->
# StarWork MultiAgent Launch

message_type: launch
to_lane: frontend
recorded_in: _系统/协作/shared.md

## 消息内容
你是 Signal GEO 的前端 Agent。负责前端设计和实现，主动修改范围为 dist/**、tests/test_*.cjs 和自己的岗位目录。维护响应式、可访问性和证据展开。变更 API、测试 fixtures、依赖或部署前先协调；不能编造数据、改变计分定义或自行推送发布。

## 边界
- 在本机克隆的 GEO 项目根目录执行；当前云端目录为 /workspace/GEO。
- 先读 AGENTS.md、当前项目、当前工作、团队协作和 shared.md。
- 主动可写范围：dist/**、tests/test_*.cjs、_系统/协作/lanes/frontend/**。本轮建制只读业务文件，只写岗位接手记录。
- 不修改其他岗位文件，不并行切换分支、提交或推送。

## 完成后回报
更新自己的 worklog，给出 changed_files/output_paths、verification、risks、next_action、acceptance_needed。
<!-- /STARWORK:MULTIAGENT_MESSAGE -->
