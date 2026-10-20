# 前端预览

本配置仅用于静态前端预览，原 Sites 和未来正式域名都不会被更新。实际 AI 请求与多人数据存储仍需后端。预览不会连接正式后台，浏览器内导入的资料仍只在当前浏览器处理。

## 一次性连接 Netlify

1. 合并本分支到 GitHub 的 main；当前聊天没有 GitHub API 权限，不能代建或合并 Pull Request。
2. 打开 https://app.netlify.com/ ，用你自己的账号登录（可用 Google）。创建从 Git 仓库导入的新项目，选择 GitHub 并授权访问 saml1nhchen-ops/GEO。不要把密码或令牌发到聊天或放进仓库。
3. 选择 main，站点名可用 signal-geo-preview 加一个独特后缀。netlify.toml 自动设置构建命令与 preview-dist 发布目录，不需要 Python、模型密钥或后台连接。若界面没有读取配置，填写下列构建命令和发布目录。
4. 在站点的部署设置中确认启用 Deploy Previews。具体按钮名称可能随 Netlify 界面更新；仓库还需有对应 GitHub App 的访问权限。首次部署成功后，默认 netlify.app 地址就是这套前端的预览入口。
5. 以后从 main 创建分支修改，通过 Pull Request 提交。Netlify 成功部署后，PR 的检查/部署信息将提供此次修改的独立预览链接；失败时先查看构建日志。

构建命令：

```sh
node tests/test_frontend.cjs && node tests/test_diagnostic.cjs && node deploy/build-preview.cjs
```

发布目录：preview-dist

这里 Netlify 的主分支部署也是“预览站点”的入口；不要绑定正式域名。它和 PR 的独立 Deploy Preview 都可以随代码更新。Release 才更新正式站需要另一个生产部署流程，目前尚未配置。

Netlify 的额度、费用、私有仓库连接和访问保护功能以账号当前计划为准。不要默认认为私有 GitHub 仓库会使预览网址也私有；若要限制访问，先确认可用的站点访问控制。不要把真实客户资料、API 密钥或私有报告写入 dist。

## 不连接托管平台也能检查

```sh
node deploy/build-preview.cjs
python3 -m http.server 8780 --bind 127.0.0.1 --directory preview-dist
```

在本机浏览器访问 http://127.0.0.1:8780/ ，Ctrl+C 停止。这个 Python 命令只提供静态文件，不运行分析后台。

GitHub Actions 的 Frontend preview package 在相关 PR 上生成可下载的 frontend-preview 压缩包，保留七天；它是文件产物，不是可点击的托管网址。下载解压后，也可用本机静态文件服务查看。手动触发需工作流先存在于默认分支。

## 构建边界

仅从 dist 复制前端资源，拒绝符号链接、隐藏文件和非前端扩展名，不复制运行数据或 .openai 配置。生成预览提示和禁止搜索引擎索引的标记，不改写原 dist。缺失 API 应返回 404，不用通配的 SPA 路由伪装成成功。
