# 部署、配置与维护

[返回项目说明](../README.md) · [使用手册](user-guide.md) · [开发说明](development.md)

项目通过 Linux 脚本启动和关闭，命令除明确标注 PowerShell 外，均在项目根目录的 Linux / Ubuntu WSL 终端执行。当前电脑的后端与周老师 OJ 采集器在 Linux，ACGO 使用专用 Windows Edge。WSL 中检测到标准路径的 Windows Node 时，ACGO 子进程优先使用它，否则使用 Linux Node。后端使用 Linux 文件锁，不能直接当作原生 Windows Python 项目启动。

## 新环境安装

准备 Python 3.12、支持 Vite 的 Node.js 20.19+ 或 22.12+（项目缺少 Node 时会安装工作区 Node 24）、中文字体及 Chromium 依赖。安装脚本需要联网下载依赖。

```bash
sudo apt-get update
sudo apt-get install -y python3-venv libnspr4 libnss3 libasound2t64 fonts-noto-cjk
bash scripts/setup.sh
```

上述系统包对应当前 Ubuntu；其他版本按系统包名及 Playwright 诊断补装。`setup.sh` 创建 `.venv`，按 Python / npm 锁文件安装、构建前端并安装 Chromium。`.tools/node` 的自动安装仅适用于 Linux x64，并校验官方包哈希；已有 Node 但版本过旧时应先升级。依赖成功后按下节启动后台服务。

ACGO 连接 Windows Edge 的新电脑还应在 Windows 安装 Node.js 20+ 到标准路径 `C:\Program Files\nodejs\node.exe`，让采集进程直接访问 Windows 的 `127.0.0.1:9223`；Linux 安装脚本不安装 Windows Node。回退 Linux Node 时需要 WSL 能访问同一调试端口，不要为此把浏览器调试端口暴露到局域网。

后端默认 `127.0.0.1:8765`，不需要另开 Vite。前端在 `frontend/dist/`；源代码修改后需重新构建。启动后 [健康接口](http://localhost:8765/api/health) 应返回 `status: ok`，密钥状态为 `api_configured`，参考卷数量为 `reference_papers`。

## 启动、关闭与迁移目录

在 Linux / WSL 终端执行：

```bash
./feedback.sh start
./feedback.sh stop
./feedback.sh status
```

统一入口 `feedback.sh` 用 `start`、`stop`、`status` 控制服务，不传参数时默认启动；`./feedback.sh --help` 查看选项。`start` 将服务与终端会话分离，输入连接到 `/dev/null`，输出写入日志；启动就绪后命令返回，关闭终端后仍运行，直到执行 `stop`。电脑重启、终止整个 WSL 发行版或 `wsl --shutdown` 也会结束服务；本脚本不设置开机自启。

脚本按自身位置确定项目目录，可从任何工作目录调用，路径可含空格。例如：`/home/algor/feedback/feedback.sh start`。安装依赖或前端构建缺失时会明确提示先运行安装脚本。Git 保存了执行权限；如果通过不保留权限的工具复制项目，可执行 `chmod +x feedback.sh`，或直接用 `bash feedback.sh start`。

重复 `start` 不会多开服务，重复 `stop` 可以安全执行。旧版前台服务首次切换时先 `stop` 再 `start`；脚本不会把旧前台进程冒充后台服务。关闭时核对项目目录及服务命令，通过进程句柄请求正常退出；其他项目不会被关闭，也不按端口强杀。默认最多等待 30 秒，超时会提示仍在收尾，可增加等待时间。已保存材料与分析阶段保留，重启后可恢复中断分析；专用 Edge 登录窗口可继续保留。

端口只在新启动时生效；更换端口先关闭原服务。示例：

```bash
./feedback.sh start --port 8766
./feedback.sh stop --timeout 60
```

此时访问 `http://localhost:8766/`。前端开发代理和检查脚本默认使用 8765，改端口时同步核对。服务标准输出和错误写入 `.run/service.log`，重新启动时上一份日志保留为 `.run/service.previous.log`；状态与锁文件也在 `.run/`，不进入 Git 或档案备份。不要在服务运行时删除该目录。启动失败先查日志；端口已被其他程序占用时会报错，不关闭那个程序。

同一项目目录只运行一份服务。不同项目副本也不要共用私有数据目录，或使用多 worker 模式：当前分析任务、采集进度和并发锁位于单进程内存。

## 密钥与配置

可参考根目录 [.env.example](../.env.example)，自行创建不进入 Git 的 `.env`。所有私有路径相对于运行环境：WSL 使用 Linux 路径。

| 配置 | 默认值或位置 | 生效规则 |
| --- | --- | --- |
| API 密钥 | 根目录 `deepseek` 文件中 `sk-…` | 本地设置优先，其次 `DEEPSEEK_API_KEY`，最后文件 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 本地设置模型优先 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 本地设置优先；首版仅允许官方 HTTPS API |
| `DEEPSEEK_CONCURRENCY` | 4 | 本地设置优先，有效值 1—8 |
| `DEEPSEEK_TIMEOUT` | 120 秒 | 单次 HTTP 请求超时；改环境后重启 |
| `DEEPSEEK_MAX_CALLS` | 48 | 基础调用预算；报告按题量、恢复阶段自动扩展，不是固定题数上限 |
| `FEEDBACK_DATA_DIR` | `data/private/` | 私有档案及设置目录；修改后重启 |
| `FEEDBACK_PORT` | 8765 | Linux shell 环境默认值；`./feedback.sh start --port` 优先；不从 `.env` 读取 |

页面保存的设置在私有目录的 `settings.json`，页面不回显 API 密钥。只改模型或并发数不会把根目录密钥复制进去；主动填写密钥才会保存。已有设置密钥继续优先，想一直用根目录文件时，不要再在页面填写另一份。

“清除密钥”会保存空密钥并禁用调用，即使根目录仍有文件也不回退。若要恢复文件或环境变量方式：先关闭程序，只从 `settings.json` 删除 `api_key` 属性，保留其他设置，再启动。不要把密钥粘贴到日志、文档或 Git 提交中。

真实分析和连接测试会访问 DeepSeek，可能产生费用。代码、题面、年龄、年级和必要学习背景会发送；程序替换已知姓名，但不承诺把任意自由文本中的所有个人信息自动匿名化。

## 两个平台的连接

ACGO 专用窗口启动命令，在 Windows 项目目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-acgo-edge.ps1
```

脚本使用 `%LOCALAPPDATA%\Feedback-ACGO\Edge-Profile`，调试地址 `127.0.0.1:9223`，与日常 Edge 分开。在这个窗口登录并保持打开。WSL 采集器检测不到连接时尝试重新启动原窗口，不代替用户登录。当前脚本使用 Edge 标准安装路径，特殊安装位置需修改脚本。Linux 独立环境的 ACGO 采集需另行提供可连接的已登录 CDP 浏览器，不能依赖 Windows 自动重开逻辑。

周老师 OJ 在导入页保存含 `key` 的管理员链接，或通过接口保存地址及密钥。配置在私有目录 `csp-exam-connection.json`；任务参数与报告来源链接只保留无密钥地址。备份不包括连接凭据。当前连接器适配 [HydraBor/csp-exam-system](https://github.com/HydraBor/csp-exam-system)，平台页面结构变化需更新解析器。

## 备份与恢复

等待采集、分析完成后，在“本地设置”下载档案备份 ZIP。包含 SQLite 数据库、确认版 HTML 和已导出 PDF；不包含 DeepSeek 密钥、设置、周老师 OJ 凭据、Edge 登录配置或公开资料。备份包含学生代码，应单独妥善保存。

恢复到**尚不存在的新目录**，不覆盖原档案：

```bash
# 先停止当前程序，再将备份放在可读取路径
.venv/bin/python scripts/restore.py /path/to/feedback-backup.zip \
  --destination /home/algor/feedback-restored
```

工具检查 ZIP 路径、允许文件、512 MB 解压上限和 SQLite 完整性。成功后在项目 `.env` 设置：

```dotenv
FEEDBACK_DATA_DIR=/home/algor/feedback-restored
```

重启核对学生、做题档案、确认版本和 PDF。设置与连接需要在新私有目录重新配置；根目录密钥仍可使用。切换回原目录时恢复原 `FEEDBACK_DATA_DIR`。不要从备份恢复成功就删除原资料，应先核对内容。

迁移电脑还需保留项目代码、`data/public/` 和所需凭据；重新安装依赖。Edge 登录配置不在 ZIP 中，新电脑重新登录。不要在服务运行时只复制 `feedback.sqlite3`，SQLite WAL 中可能还有更新；优先使用页面备份。

## 常见故障

| 现象 | 检查与处理 |
| --- | --- |
| 启动找不到 `.venv` 或前端未构建 | 在 Linux 项目目录执行 `bash scripts/setup.sh`；确认 `feedback.sh` 路径 |
| 提示旧前台服务仍在运行 | 在当前项目目录先执行 `./feedback.sh stop`，再 `./feedback.sh start` |
| 8765 已占用 | 查看 `.run/service.log` 与 `./feedback.sh status`，核对服务或改端口；不要同时运行多个实例 |
| 读取作品按钮灰色 | 新建反馈页需选学生、填写起止日期、平台学生 / 团队 / 比赛编号；按按钮下方缺项提示补齐 |
| ACGO 找不到浏览器 | 手动执行专用 Edge 脚本；核对 9223、Node 环境及 WSL 到 Windows 的连接 |
| ACGO 权限 / 登录错误 | 在专用窗口重新登录，确认能查看所选学生代码；不要用其他浏览器登录代替 |
| 周老师 OJ 登录失败 | 重新保存管理员连接；确认比赛链接来自已连接站点，包含唯一 `c` 参数 |
| 日期没有作品 | 核对实际提交日期、时区和起止范围；日期未知的快照不会当作本期可靠提交 |
| 逐题已完成，总分析失败 | 降低分析并发、检查网络 / 密钥 / 余额，再恢复分析；完整逐题结果保留 |
| 文案提示阻止确认 | 按提示改掉原题名、代码术语或无依据判断，再预览确认；不需要重做所有分析 |
| 保存提示版本已更新 | 刷新页面核对最新内容，再保存；请求携带旧 revision 会被拒绝 |
| PDF 下载失败 | 确认已安装 Chromium、系统依赖与中文字体；重试下载，确认文字仍保存 |
| 旧 PDF 没有新模板效果 | 旧确认版是排版快照；审核当前草稿并确认一个新版本 |
| 参考卷数为 0 | 检查竞赛资料是否全数有效审核；内容变化会使审核失效，按下节重新复核 |

PDF 环境修复命令：

```bash
.venv/bin/python -m playwright install chromium
# 仍缺系统依赖时，按诊断安装；下面命令可能需要 sudo
.venv/bin/python -m playwright install-deps chromium
```

## 更新公开资料

日常生成不需要重新采集真题。修改前查看 Git 差异并保留当前版本，更新后核对来源、年份、题号、时限、分值和广东线。原始抓取与交叉来源在忽略的 `data/public/raw/` 中；公开克隆没有缓存时需先收集交叉来源，再进行 AI 审核。

```bash
.venv/bin/python scripts/collect_csp.py
.venv/bin/python scripts/collect_reference_statements.py
.venv/bin/python scripts/audit_csp.py --concurrency 4
.venv/bin/python scripts/collect_acgo_collections.py
```

这些脚本会联网并修改公共资料；AI 审核会实际调用 DeepSeek。`collect_csp.py` 保留现有有效审核，收集与审核分开；题面交叉来源脚本跳过已有文件。需要更新交叉来源时先核对旧文件并通过 Git 保留，再有针对性处理。`audit_csp.py` 复用同版有效 AI 审核，`--force` 强制重审。所有真题有效审核后才开放参考卷。

年度规则目前需要维护者核对官方来源后编辑 `data/public/rules.json`，无自动更新等级线接口。未知日程、资格或省线保留未知。更新公共资料后运行开发检查，记录资料版本和来源，提交 Git；私有资料不随提交发布。
