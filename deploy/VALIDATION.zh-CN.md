# 验证说明

本次检查不会调用付费模型。测试样本是合成数据，不是 Cremo 实测结果。

## 可重复执行

- `python3 -m unittest discover -s tests -p 'test_remote*.py'`：HTTP 鉴权、白名单、额度、共享任务、关闭竞态、启动配置。
- `node tests/test_frontend.cjs`、`node tests/test_diagnostic.cjs`、`node tests/test_report_summary.cjs`、`node tests/test_question_cards.cjs`：统计、缺失数据、卡片与报告。
- 安装 Playwright 和 Chromium 后，在仓库根目录运行 `python3 -m http.server 9001 --bind 127.0.0.1`，另开终端运行 `node tests/browser_remote.cjs`。可用 `CHROMIUM_PATH` 指定浏览器。此测试拦截并模拟后台响应，检查页面行为和请求字段，不证明真实供应商可用。
- `docker build -t signal-geo-backend:cremo .`：构建完整运行依赖。若环境通过 HTTPS 代理，按其 CA 指引传入可选 BuildKit secrets `proxy_ca` / `system_ca`，不要关闭证书验证。
- 构建后运行 `python3 tests/container_remote.py`：启动独立测试容器，验证真实 HTTP 登录、注销、缺密钥状态、非 root 身份、端口映射、预算重启持久化。占用本机 18880，结束删除自己的临时容器和卷，不使用正式数据。

完整 Python 测试需要固定 NiubiGEO 的 Node/tsx 依赖。容器镜像已安装；裸宿主缺少该依赖时会有两项依赖测试失败，不能当作全部通过。

## 尚未验证

- 托管平台实际创建、HTTPS、公网连通和持久磁盘权限。
- B.AI 实时目录与模型调用。
- Cremo 官网抓取、30 道真实问题及真实报告。
- GitHub Release 自动部署、原 Sites 更新。

这些依赖真实凭据、联网策略和托管授权，不能由本地合成测试替代。

## 本轮实际结果

- 最终容器构建成功；在禁止联网的测试容器中，72 项 Python 测试通过，包含真实固定 NiubiGEO 构建与解析依赖检查。
- 4 个前端 Node 检查脚本通过。
- Chromium 合成后台页面验证通过：请求白名单、登录凭证仅在内存、额度/未就绪/断网/401、鉴权导出、问题弹窗、默认工作台全览。
- 真实容器生命周期验证通过：3 个私有服务启动、UID 10001、仅公开网关端口、登录/注销、缺密钥时不可分析、预算跨重启保留、旧会话重启失效。
- 独立验收发现关闭期间仍可能提交新任务，已修复并独立复验通过：关闭发生在计划阶段时不预约额度、不提交任务；已获准提交会先记录任务再停止。
- 无真实模型调用，无正式部署，无模型账单金额或 Cremo 真实评分。
