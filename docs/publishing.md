# GitHub 发布与后续更新

[返回项目说明](../README.md) · [开发说明](development.md) · [部署维护](operations.md)

正式仓库：[HydraBor/FeedBack](https://github.com/HydraBor/FeedBack)。代码使用 [MIT License](../LICENSE)，第三方代码、竞赛资料与平台元信息的范围见[第三方说明](../THIRD_PARTY_NOTICES.md)。

## 上传范围

| 上传 | 留在本机，不上传 |
| --- | --- |
| 后端、前端、采集器、模板、维护脚本 | 根目录 `deepseek`、真实 `.env` 和密钥文件 |
| Python / npm 锁文件与 `.env.example` | `data/private/` 下的学生档案、代码、设置、管理员连接、HTML、PDF |
| 使用、维护、评估、开发及接口文档 | SQLite、备份 ZIP、输出目录、浏览器登录配置 |
| 运行所需整理参考库、规则、词表、题单、审核与核对记录 | `data/public/raw/` 原始抓取副本、`data/public/papers/` 下载试卷 |
| 单元测试、CI、原爬虫许可及来源 | `.venv`、Node / Chromium 运行时、node_modules、前端构建产物、临时检查文件 |

第一次公开使用经检查的当前快照作为 `main` 首个提交；旧本地历史中出现过学生姓名，因此保存在本机 `local-history-pre-github` 分支，没有上传。这个本地分支不得使用 `git push --all` 或 `git push --mirror` 推送。正式开发继续在 `main`。

公开仓库不包含用户密钥、账号登录和学生作品。克隆后安装依赖、配置自己的 DeepSeek 密钥和 OJ 权限即可运行。原始交叉资料缓存缺失时，可先运行 `collect_reference_statements.py`，再按维护流程重新 AI 审核。

## 后续推送

在 Ubuntu 项目根目录检查，确认仅包含准备公开的修改：

```bash
git status --short
git diff --check
git diff
# 明确选择文件，避免盲目加入测试数据
git add README.md backend/ frontend/ docs/ scripts/ tests/
git diff --cached --stat
git commit -m "Describe the change"
git push origin main
```

新建许可、配置或数据文件时单独核对并加入。不要上传真实学生姓名、ID、代码、报告或完整排错结果；`.gitignore` 不能保护已经被跟踪的文件，也不能清除旧提交中的内容。发现误提交先停止推送并修复，真实凭据已经公开时还需在所属平台更换。

当前电脑 GitHub 凭据位于 Windows Git Credential Manager；WSL Git 若没有配置凭据助手，推送可能要求登录。可以在 Windows PowerShell 使用已安装 Git，并为此 WSL 仓库设置单次安全目录参数：

```powershell
& 'C:\Program Files\Git\cmd\git.exe' `
  -c 'safe.directory=//wsl.localhost/Ubuntu/home/algor/feedback' `
  push origin main
```

路径按实际目录修改，不需要把 GitHub token 写进 remote URL、项目文件或命令中。远端非快进冲突先获取并核对远端修改，不使用强制推送覆盖。

## 自动检查

`.github/workflows/ci.yml` 在 main 推送及 PR 时安装锁定依赖、执行后端测试、采集核心测试和前端构建。CI 仅用临时数据、mock API，不访问真实学生作品，不需要 DeepSeek 或 OJ 密钥。PDF 视觉检查及外部平台真实采集仍按本地维护流程执行。
