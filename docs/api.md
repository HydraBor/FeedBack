# 接口说明

[返回项目说明](../README.md) · [开发说明](development.md) · [使用手册](user-guide.md)

服务默认 `http://localhost:8765`。运行中的 [OpenAPI](http://localhost:8765/docs) 和 `/openapi.json` 是字段约束的直接来源；严格模型定义在 [models.py](../backend/models.py)，路由实现见 [app.py](../backend/app.py)。示例编号是占位数据，使用时换成真实档案及任务。

## 通用约定

- 当前 API 仅供本机工作台，不提供公网账号鉴权。Host 必须为本机地址，浏览器 Origin 必须同站，跨站请求拒绝。
- 所有 POST、PUT、DELETE 请求发送 `Content-Type: application/json`，无参数操作也发送 `{}`。
- 学生、反馈、档案、确认版 ID 是字符串；ACGO 雪花 ID 也保留字符串，不能转浮点数。
- 日期使用 `YYYY-MM-DD`，提交时间须带时区，按 `Asia/Shanghai` 筛选起止日。
- 输入模型拒绝未知字段。完整上限、可选字段及枚举以 OpenAPI 为准；题目列表、提交列表无数量上限。
- 保存材料或审核携带最新 `revision`，从读取反馈的结果取得；旧版本返回 400，避免覆盖他人或另一个窗口的修改。

## 当前路由

| 方法与路径 | 功能 |
| --- | --- |
| `GET /api/health` | 运行状态、密钥是否配置、分析方式、时区及参考卷数 |
| `GET /api/students?q=` | 姓名查找和学生列表 |
| `POST /api/students` | 建立学生档案 |
| `PUT /api/students/{sid}` | 更新学生信息 |
| `DELETE /api/students/{sid}` | 携带 `confirm_name` 删除学生及关联资料 |
| `GET /api/acgo/status` | 检查专用浏览器连接，必要时尝试自动重开 |
| `GET /api/zhou-oj/connection` | 读取不含密钥的连接状态 |
| `PUT /api/zhou-oj/connection` | 保存管理员地址与密钥 |
| `POST /api/acgo/imports` | 单一类型的多份 ACGO 材料导入预览 |
| `GET /api/acgo/imports/{ident}` | 查询 ACGO 导入进度、结果或错误 |
| `DELETE /api/acgo/imports/{ident}` | 取消导入并删除临时预览 |
| `POST /api/zhou-oj/imports` | 按比赛号导入周老师 OJ 材料预览 |
| `GET /api/zhou-oj/imports/{ident}` | 查询周老师 OJ 导入 |
| `DELETE /api/zhou-oj/imports/{ident}` | 取消对应导入 |
| `POST /api/practice-archives/imports` | 混合多平台导入，成功后自动保存做题档案 |
| `GET /api/practice-archives/imports/{ident}` | 查询建档导入 |
| `DELETE /api/practice-archives/imports/{ident}` | 取消建档导入 |
| `GET /api/practice-archives?student_id=` | 做题档案摘要列表 |
| `GET /api/practice-archives/{ident}` | 档案完整题面、代码、过程和来源 |
| `GET /api/reports?student_id=` | 反馈摘要列表 |
| `POST /api/reports` | 保存反馈输入，尚不触发分析 |
| `PUT /api/reports/{fid}/input` | 按 revision 修改本期材料，变更后清除旧分析、等待重新分析 |
| `GET /api/reports/{fid}` | 输入、阶段、分析、草稿、错误、revision 与确认版本 |
| `POST /api/reports/{fid}/generate` | 开始或恢复分析 |
| `PUT /api/reports/{fid}/review?confirm=` | 保存审核；`confirm=true` 新增确认版本 |
| `POST /api/reports/{fid}/rewrite` | 复用评分与定位，更新文案及可选训练建议 |
| `GET /api/reports/{fid}/preview?version_id=` | 草稿或指定确认版 HTML |
| `POST /api/reports/{fid}/preview` | 渲染传入审核内容，未持久化 |
| `GET /api/reports/{fid}/versions/{vid}/pdf` | 下载对应确认版 PDF |
| `GET /api/settings` | 脱敏设置，不回传密钥 |
| `PUT /api/settings` | 更新密钥、模型、官方地址或分析并发 |
| `POST /api/settings/test` | 实际调用 DeepSeek 测试结构化连接 |
| `GET /api/library` | 词表、能力、真题、规则、题单及审核开放统计 |
| `PUT /api/library/problems/{pid}` | 编辑题面、题解、标签、来源及复核状态 |
| `GET /api/backup` | 下载不含密钥和连接文件的档案 ZIP |

旧 `/api/csp-exam/connection`、`/api/acgo/archives` 等别名已移除；本地评测路由已删除。自招只保留模型字段，没有分析端点。

## 学生和做题档案示例

建立学生，返回 `id`：

```json
{
  "name": "示例学生",
  "age": 12,
  "grade": "初一",
  "acgo_user_id": "1000001",
  "background": "",
  "note": ""
}
```

向 `POST /api/practice-archives/imports` 发送混合建档请求；`student_id` 换成上一步返回的值，姓名和平台 ID 必须匹配。仅周老师 OJ 时 ACGO 字段可为空。

```json
{
  "name": "示例学生",
  "student_id": "替换为已有学生档案ID",
  "user_id": "1000001",
  "team": "2000000000000000000",
  "homework": "101,102",
  "contest": "",
  "csp_contests": ["c1", "c2"],
  "csp_exam_number": "",
  "start_date": "2026-10-01",
  "end_date": "2026-10-05",
  "contest_independent": true,
  "concurrency": 3
}
```

日期同时为 `null` 时，建档接口按可核实提交的实际日期整理；直接导入预览的 ACGO / 周老师 OJ 接口必须给日期。`homework`、`contest` 支持英文逗号分隔编号或 ACGO 链接；`csp_contests` 为数组，各项也可包含逗号分隔编号。

接口立即返回任务对象（HTTP 200），含 `id`、`status: running`、`progress`、`result`、`error`。随后查询 `/api/practice-archives/imports/{id}`，间隔约 1—2 秒即可：

- `running`：继续等待。
- `completed`：`result` 含 `archive_id`、`student_id`、起止日期、题目 / 提交 / 任务数量和警告；再读档案详情核对所有失败项。
- `failed`：显示 `error`，处理连接或输入问题后重新导入。
- `cancelled`：导入取消；DELETE 同时移除临时任务，后续查询可为 404。

成功建档会持久化，内容相同会复用档案。直接 `/api/acgo/imports`、`/api/zhou-oj/imports` 仅返回预览材料，不自动保存做题档案。临时任务只在内存，服务重启或完成约一小时后预览失效，不要把任务 ID 当作档案 ID。

## 反馈、分析和确认

`POST /api/reports` 最小示例（仅知识描述也可分析，但定位证据通常较少）：

```json
{
  "student_id": "替换为已有学生档案ID",
  "start_date": "2026-10-01",
  "end_date": "2026-10-05",
  "reference_date": "2026-10-09",
  "tracks": ["J", "S"],
  "target_year": 2026,
  "topics": "模拟、枚举",
  "problems": [],
  "mode": "live"
}
```

导入档案作品时，将选中 `content.problems` 放入 `problems`，保留原 `source`、提交与完成条件。平台采集时段必须与本期日期一致，学生 ID 与档案归属必须匹配；不要只复制主代码、丢掉来源或把修改代码继承成原 AC。

创建返回反馈 `id`。同一 `student_id + start_date + end_date + mode` 只保留一份当前报告：相同输入复用原 ID 和分析；输入改变时覆盖本期材料、增加 revision、清除旧分析缓存并回到 `draft`，完整旧稿和确认版本保留。不同学习时段分别保存；演示模式与真实报告隔离。分析或文案更新进行中拒绝替换材料。

仅在返回状态为 `draft` 或 `failed` 时，向 `/api/reports/{id}/generate` POST `{}`，再 GET 反馈查看状态与阶段；已完成或正在运行时直接打开原报告。失败时再次 generate 恢复，已通过的阶段复用。修改已有报告推荐 PUT `/input`，携带最新 revision，学生、时段及模式不能改变。

更新文案请求：

```json
{"refresh_training": true}
```

发送到 `/api/reports/{id}/rewrite`；`false` 仅改家长文字、保留训练建议，默认 `true` 刷新建议。覆盖当前报告的文字与建议，ID 与列表数量不变，评分与等级不重新计算，原确认版本仍在该报告内部。需已有真实分析，演示模式不支持这个入口。

旧版本重复报告在启动时保留最近创建的一份作为当前报告，其余旧稿用 `superseded_by` 指向它并从列表移除，不删除原始材料或确认文件。GET 旧报告返回这个字段，界面自动打开当前报告；旧稿的修改接口拒绝写入。当前报告的 `versions` 同时列出合并前的确认版本，下载与预览仍使用各版本原始材料和 HTML 快照。

保存审核时从详情取得 `draft` 完整对象与最新 `revision`，编辑后发送到 `/review`。`report` 必须是符合 `ParentReport` 的完整对象，可用 JavaScript 构造：

```javascript
const body = {revision: detail.revision, report: editedDraft};
```

普通保存更新草稿；`?confirm=true` 校验评分、题单与文案并新增版本，返回的 `versions` 包含 `id` 和 `revision`。下载用确认版 `id`，不是报告 ID 或 revision。POST 预览使用相同审核外层结构，返回 HTML，不保存、不确认。

家长用词与表达检查返回 `warnings`，属于讲师手动修改的提醒，不让分析失败或自动重写，不阻止确认。JSON 结构、评分证据、题单来源和所选组别等约束仍会拒绝无效内容。恢复因旧文风检查而失败的报告时，复用已保存的完整、结构有效的家长回复及分析阶段，不为措辞重复调用 AI。

## 设置、资料与错误

保存周老师 OJ 连接可提交 `admin_url`（含 key），或 `base_url` 加 `admin_key`。不要把真实密钥写入接口示例、命令历史或报告链接。读取连接只返回站点与是否配置。

设置 PUT 可只提交 `{"analysis_concurrency": 4}`，不带 `api_key` 就不复制或修改密钥。显式 `api_key: ""` 禁用 API，根目录文件也不会回退；`null` 忽略。题库编辑允许字段见 app.py；内容更改使审核指纹失效，`review_confirmed: true` 表示讲师已复核当前内容。全部题目有效审核后才开放参考卷。

| 状态码 | 常见含义 |
| --- | --- |
| 400 | 日期、作品归属、revision、状态、文案或业务条件不满足 |
| 403 | 非本机 Host、跨站 Origin / Fetch 请求 |
| 404 | 学生、反馈、确认版不存在，或临时导入预览过期 |
| 415 | 写请求未使用 JSON Content-Type |
| 422 | 请求结构、类型、未知字段或模型约束不满足 |
| 503 | PDF 渲染或前端构建环境未就绪 |

导入 / 分析的异步失败通过任务或反馈的 `status`、`error` 返回，查询本身可能仍为 HTTP 200。前端必须同时检查 HTTP 错误和业务状态。备份在任务运行时拒绝，删除学生需精确 `confirm_name`，分析中也不能删除。
