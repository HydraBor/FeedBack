# 成长反馈 · CSP 教学工作台

本机运行的学生反馈系统：讲师建立档案，从 ACGO 和周老师 OJ 导入指定日期的题面、代码与已有评测结果，DeepSeek 分阶段分析，再由讲师预览、修改和确认，生成家长看得懂的 A4 PDF。

[GitHub 仓库](https://github.com/HydraBor/FeedBack) · [MIT 代码许可](LICENSE) · [自动检查](https://github.com/HydraBor/FeedBack/actions/workflows/ci.yml)

## 安装与启动

推荐 Windows + Ubuntu WSL。在 Ubuntu 终端克隆并安装（系统依赖、Windows Node 与 Edge 要求见[维护手册](docs/operations.md#新环境安装)）：

```bash
git clone https://github.com/HydraBor/FeedBack.git feedback
cd feedback
bash scripts/setup.sh
```

首次真实分析前配置自己的 DeepSeek 密钥；没有密钥也可使用明确标记的演示模式检查流程。

在项目目录的 Windows PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\feedback.ps1 start
powershell -ExecutionPolicy Bypass -File .\feedback.ps1 stop
powershell -ExecutionPolicy Bypass -File .\feedback.ps1 status
```

`start` 在后台启动，关闭终端后仍运行；`stop` 正常关闭，`status` 查看状态。打开 [教学工作台](http://localhost:8765/)。重复启动不会多开服务，日志保存在 `.run/service.log`。旧版前台服务首次切换时，先执行 `stop`，再执行 `start`。

Ubuntu / WSL 终端使用同一服务控制程序：

```bash
.venv/bin/python scripts/service.py start
.venv/bin/python scripts/service.py stop
.venv/bin/python scripts/service.py status
```

Windows 下推荐 PowerShell 入口，它还会保留独立的 WSL 宿主供 ACGO 调用 Windows Node 与 Edge。脚本自动识别项目目录，只关闭该目录的服务；已保存档案和分析阶段保留。端口、超时和日志说明见[维护手册](docs/operations.md#启动关闭与迁移目录)。

DeepSeek 密钥可继续放在根目录的 `deepseek` 文件。读取顺序为 **本地设置 → 环境变量 → 根目录文件**；修改并发数或模型不会自动复制文件密钥。已有本地设置密钥仍有优先权，详见[配置说明](docs/operations.md#密钥与配置)。

首次导入 ACGO，需要在专用 Edge 登录：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-acgo-edge.ps1
```

## 日常使用

1. 建立或选择学生档案，核对姓名、ACGO ID、年龄与年级。
2. 在“导入做题档案”填写多份作业或比赛编号，用英文逗号分隔；可同时导入两个平台的材料。检查日期、读取失败项与未提交题目。
3. 选择本期题目，带入反馈，填写目标 CSP 年份、J / S 组别及完成条件，保存或生成。
4. 审核知识评分、等级依据、文案和题单。需要时恢复失败的分析，或只更新文案与建议。
5. 确认版本，下载 PDF。后续修改会形成新版本，已有确认内容和排版快照保留。

## 当前功能与边界

- 学生档案、做题档案、阶段反馈与更早时段已确认材料的引用；同名学生独立保存。
- ACGO 多作业、多比赛，以及周老师 OJ 指定比赛导入；每份作业或比赛独立采集进程，保留非 AC 历史及未提交题面，不设题目或提交数量上限。
- 逐题、分批汇总及历年卷分析，受控并发、分阶段保存、失败后恢复。
- 六项能力分析、知识掌握图、保守 CSP 等级定位和配套题单。图表只用本期有效评分最高的六项，一两项时使用条形图。
- 家长正文采用已选定的 A 版自然讲师口吻，不罗列原题名或代码细节；标题可编辑，默认姓名；评分注解三行对齐，题单四列排列，内容多时自动分页。
- 本机不编译、运行或重新评测学生代码；使用 OJ 对原始提交的已有结果与静态分析。深圳自招停用，仅保留相关数据字段。

公开资料基准为 **2026-10-09**：2019—2025 第二轮 58 道题完成 AI 交叉审核，14 套 J/S 参考卷开放；广东各年一、二、三等线已核实。ACGO 已记录 40 份题单。新评估覆盖所选组别的全部可用历年卷，不只对照 2025 年。审核、定位及资料维护规则见[评估依据](docs/assessment.md)。

系统监听本机地址，当前没有多人账号和公网部署功能。真实分析会将学习材料发送给 DeepSeek；已知学生姓名替换为占位称呼，其他个人信息需讲师检查。私有档案和密钥不进入 Git。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [使用手册](docs/user-guide.md) | 建档、日期、多平台导入、恢复分析、审核、PDF 和日常问题 |
| [部署、配置与维护](docs/operations.md) | 安装、启动、密钥、备份恢复、连接故障和资料更新 |
| [评估依据与数据规则](docs/assessment.md) | 完成条件、未提交、评分、历史资料、历年 CSP 定位及审核开放条件 |
| [家长反馈写作规则](docs/parent-feedback-writing.md) | A 版文风、完整提示词链路、证据与自然语言要求 |
| [开发说明](docs/development.md) | 模块、数据流、状态、版本、修改与验证约定 |
| [接口说明](docs/api.md) | 当前路由、请求示例、异步导入、版本控制与错误处理 |
| [GitHub 发布与更新](docs/publishing.md) | 上传范围、敏感文件排除、公开历史、凭据与 CI |
| [收尾验证记录](RELEASE_CHECKS.md) | 本轮复查结果、此前真实验证和已知边界 |

## 开发检查

以下命令在项目根目录的 Ubuntu / WSL 终端执行；安装步骤见维护手册。

```bash
export PATH="$PWD/.tools/node/bin:$PATH"
.venv/bin/python -m pytest -q
npm --prefix integrations/acgo test
npm --prefix frontend run build
.venv/bin/python scripts/check_pdf.py
```

接口的自动生成文档在服务启动后的 [OpenAPI 文档](http://localhost:8765/docs)。会创建演示档案、读取外部平台或实际调用 DeepSeek 的检查脚本应在独立数据目录执行，具体见[开发检查说明](docs/development.md#检查与测试)。

## 许可与资料

原创程序与说明文档采用 [MIT License](LICENSE)。原爬虫辅助代码保留原 MIT 许可；竞赛题面、第三方题解与平台资料遵循各自来源及授权，不因本项目开源而自动成为 MIT 数据，见[第三方说明](THIRD_PARTY_NOTICES.md)。仓库不分发密钥、学生材料、浏览器登录状态、运行依赖、原始抓取缓存或下载试卷；保留本机生成所需的整理参考库。
