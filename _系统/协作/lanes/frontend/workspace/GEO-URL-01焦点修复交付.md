# GEO-URL-01 焦点循环修复

2026-10-21；前端修复已完成，待独立验收复验，不宣布功能通过。

## 原因与修改

独立验收在问题弹窗中观察到 Tab 从关闭按钮经过两个 summary 后进入 BODY 和背景导航。原 `dist/app.js` 仅收集 button/a/input/textarea/select，遗漏 summary，也将闭合 details 中的隐藏链接计入末尾控件。

- `dist/app.js`：新增共享 `overlayTabStops(dialog)`，收集 summary、显式 tabindex 及可编辑控件；排除 disabled（含禁用 fieldset）、inert、负 tabindex、CSS 隐藏内容和闭合 details 中首 summary 以外的控件。真实 Chromium 可对闭合 details 内容返回 layout rect，因此额外检查 details 祖先，不只依赖尺寸。每次 Tab 重新计算，支持动态展开内容。
- 正向/反向 Tab 在首尾循环；初始焦点位于 dialog 容器或外部时将其导回；无可用控件时保留在 dialog 容器。Escape 与现有关闭/题卡焦点恢复继续保留。
- `dist/index.html`：app.js 资源版本更新为 v9，避免缓存旧焦点逻辑。
- `tests/test_overlay_focus.cjs`：通过真实 Python Playwright + Chromium 执行共享 app.js，没有 mock 选择器，不访问模型或 API，也不修改公共 fixture/其他岗位浏览器脚本。

## verification

`node tests/test_overlay_focus.cjs` 通过：原 modal 与 drawer 各12次正向Tab、12次Shift+Tab严格循环；折叠区展开/收起、隐藏/禁用/inert控件、焦点意外外移后纠正、无控件弹窗、Escape/关闭按钮返回触发控件均通过，browser_errors=[]。

证据：`_系统/协作/lanes/frontend/workspace/evidence/overlay-focus-chromium.json`，由实际浏览器焦点序列生成。

`node tests/test_frontend.cjs`、`node tests/test_diagnostic.cjs`、`node tests/test_report_summary.cjs`、`node tests/test_question_cards.cjs`、`node --check dist/app.js` 全部退出码0。

## 回报

- changed_files/output_paths：上列3个业务/测试文件，本说明、前端worklog及证据文件。
- risks：本岗位真实浏览器定向测试不替代完整问题弹窗的独立复验；完整任务fixture窗口由验收和根协调管理，未并行改变其服务。
- next_action：根协调在验收释放fixture窗口后，对最终文件安排真实问题弹窗正反Tab及原抽屉复验；产品接收结果后决定是否通过。
- acceptance_needed：是，GEO-URL-01需独立复验关闭。
